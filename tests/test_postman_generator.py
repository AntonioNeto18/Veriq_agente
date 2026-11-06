import json

import pytest

from agent_veriq.config import INVALID_CREDENTIAL
from agent_veriq.config import POSTMAN_SCHEMA_URL as SCHEMA_URL
from agent_veriq.core.openapi_loader import load_spec_text
from agent_veriq.core.openapi_parser import parse_spec
from agent_veriq.core.postman_generator import (
    CollectionGenerationError,
    CollectionOptions,
    collection_summary,
    generate_collection,
    write_collection,
)
from agent_veriq.core.postman_validator import validate_collection

ALL_FIXTURES = ("users_v3_0.yaml", "users_v3_1.json", "petstore_v2.yaml", "security_mixed.yaml", "incomplete.yaml")


def _requests(items):
    for item in items:
        if "request" in item:
            yield item
        else:
            yield from _requests(item["item"])


def _request(collection, name_fragment):
    return next(item for item in _requests(collection["item"]) if name_fragment in item["name"])


def _variables(collection):
    return {variable["key"]: variable["value"] for variable in collection.get("variable", [])}


def _script(item):
    return "\n".join(item["event"][0]["script"]["exec"])


@pytest.mark.parametrize("name", ALL_FIXTURES)
@pytest.mark.parametrize("scenarios", [False, True])
def test_collections_validate_against_official_schema(load_fixture, name, scenarios):
    collection = generate_collection(load_fixture(name), options=CollectionOptions(include_scenarios=scenarios))
    assert validate_collection(collection) == []
    assert collection["info"]["schema"] == SCHEMA_URL
    json.loads(json.dumps(collection))


def test_scope_by_operation_ids_tag_and_auth(load_fixture):
    spec = load_fixture("users_v3_0.yaml")
    only_create = generate_collection(spec, operation_ids=["createUser"])
    assert [item["name"] for item in _requests(only_create["item"])] == ["Cadastra um usuário"]
    public = generate_collection(spec, auth_status="none_declared")
    assert [item["request"]["url"]["raw"] for item in _requests(public["item"])] == ["{{baseUrl}}/health"]
    by_tag = generate_collection(spec, tag="users")
    assert [folder["name"] for folder in by_tag["item"]] == ["users"]
    assert collection_summary(by_tag)["requests"] == 4
    with pytest.raises(CollectionGenerationError, match="No operation"):
        generate_collection(spec, tag="inexistente")


def test_url_path_variables_query_and_headers(load_fixture):
    collection = generate_collection(load_fixture("users_v3_0.yaml"))
    get_user = _request(collection, "GET /users/{userId}")
    url = get_user["request"]["url"]
    assert url["path"] == ["users", ":userId"]
    assert url["variable"] == [{"key": "userId", "value": "1"}]
    list_users = _request(collection, "Lista usuários")["request"]
    assert list_users["url"]["query"] == [{"key": "limit", "value": "1", "disabled": True}]
    assert list_users["url"]["raw"] == "{{baseUrl}}/users"
    assert {"key": "X-Request-Id", "value": "string", "disabled": True} in list_users["header"]
    assert _variables(collection)["baseUrl"] == "https://api.example.com/v1"


def test_json_body_and_success_assertions(load_fixture):
    create = _request(generate_collection(load_fixture("users_v3_0.yaml")), "Cadastra")
    body = create["request"]["body"]
    assert body["mode"] == "raw" and json.loads(body["raw"])["email"] == "user@example.com"
    assert {"key": "Content-Type", "value": "application/json"} in create["request"]["header"]
    script = _script(create)
    assert "oneOf([201])" in script
    assert '["name", "email", "id"]' in script
    assert "suggested by veriq" in create["request"]["description"]


def test_no_status_assertion_without_documented_success(load_fixture):
    collection = generate_collection(load_fixture("incomplete.yaml"))
    create = _request(collection, "POST /orders")
    assert "pm.expect" not in _script(create)
    assert "No documented 2xx response" in _script(create)


def test_swagger2_multipart_and_query_api_key(load_fixture):
    collection = generate_collection(load_fixture("petstore_v2.yaml"))
    upload = _request(collection, "POST /pets/{petId}/photo")["request"]
    assert upload["body"]["mode"] == "formdata"
    assert {"key": "file", "type": "file", "src": []} in upload["body"]["formdata"]
    assert upload["auth"]["type"] == "basic"
    list_pets = _request(collection, "GET /pets")["request"]
    assert list_pets["auth"] == {"type": "apikey", "apikey": [
        {"key": "key", "value": "api_key", "type": "string"},
        {"key": "value", "value": "{{apiKeyApiKey}}", "type": "string"},
        {"key": "in", "value": "query", "type": "string"},
    ]}
    assert _variables(collection)["baseUrl"] == "https://petstore.example.com/api"


def test_auth_mapping_for_mixed_security(load_fixture):
    collection = generate_collection(load_fixture("security_mixed.yaml"))
    assert _request(collection, "/public")["request"]["auth"] == {"type": "noauth"}
    oauth = _request(collection, "/admin")["request"]["auth"]
    attributes = {attribute["key"]: attribute["value"] for attribute in oauth["oauth2"]}
    assert attributes["accessToken"] == "{{oauthAccessToken}}"
    assert attributes["grant_type"] == "authorization_code"
    assert attributes["scope"] == "admin"
    assert attributes["accessTokenUrl"] == "https://auth.example.com/token"

    combined = _request(collection, "/combined")["request"]
    assert combined["auth"]["type"] == "apikey"
    assert combined["url"]["query"] == [{"key": "api_key", "value": "{{apiKeyQueryApiKey}}"}]

    cookie = _request(collection, "/cookie")["request"]
    assert {"key": "Cookie", "value": "session={{apiKeyCookieApiKey}}"} in cookie["header"]

    unknown = _request(collection, "/unknown")["request"]
    assert "auth" not in unknown and "indeterminate" in unknown["description"]
    alternatives = _request(collection, "/alternatives")["request"]
    assert "Declared authentication alternatives not applied: oauth" in alternatives["description"]


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_credentials_are_never_filled(load_fixture, name):
    collection = generate_collection(load_fixture(name))
    for key, value in _variables(collection).items():
        if key != "baseUrl":
            assert value == "", key


def test_scenarios_folder_and_assertions(load_fixture):
    collection = generate_collection(load_fixture("users_v3_0.yaml"), operation_ids=["createUser"],
                                     options=CollectionOptions(include_scenarios=True))
    folder = collection["item"][0]["item"][1]
    assert folder["name"] == "Scenarios: Cadastra um usuário"
    scenarios = {item["name"].split("]")[0][1:]: item for item in folder["item"]}

    no_auth = scenarios["createUser-02"]
    assert no_auth["request"]["auth"] == {"type": "noauth"}
    assert "oneOf([401])" in _script(no_auth)

    invalid = scenarios["createUser-03"]["request"]["auth"]
    assert invalid["bearer"][0]["value"] == INVALID_CREDENTIAL

    missing_name = scenarios["createUser-05"]
    assert "name" not in json.loads(missing_name["request"]["body"]["raw"])

    hypothesis = next(item for item in folder["item"] if "unaccepted Content-Type" in item["name"])
    assert "pm.test.skip" in _script(hypothesis) and "pm.expect" not in _script(hypothesis)
    assert hypothesis["request"]["body"]["raw"] == "plain text"


def test_validator_rejects_literal_credentials_and_bad_structure():
    collection = {
        "info": {"name": "x", "schema": SCHEMA_URL},
        "item": [{"name": "a", "request": {"method": "GET", "url": "{{baseUrl}}/a",
                                           "auth": {"type": "bearer", "bearer": [{"key": "token",
                                                                                  "value": "eyJreal"}]}}}],
    }
    assert any("credential 'token'" in error for error in validate_collection(collection))
    assert validate_collection({"info": {"name": "x"}, "item": []})


def test_write_collection_is_confined(tmp_path, load_fixture):
    collection = generate_collection(load_fixture("users_v3_1.json"))
    path = write_collection(collection, tmp_path, "../../fora/minha coleção")
    assert path.parent == tmp_path.resolve()
    assert path.name == "minha_cole_o.postman_collection.json"
    assert json.loads(path.read_text(encoding="utf-8"))["info"]["name"] == "Users API 3.1"


def test_server_variables_and_relative_servers():
    spec = parse_spec(load_spec_text("""
openapi: 3.0.0
info: {title: t, version: '1'}
paths:
  /a:
    get:
      responses:
        2XX: {description: ok}
"""))
    collection = generate_collection(spec)
    assert _variables(collection)["baseUrl"] == ""
    assert "within(200, 299)" in _script(next(_requests(collection["item"])))
