from agent_veriq.core.models import Severity, SpecVersion
from agent_veriq.core.spec_store import SpecNotLoadedError, SpecStore
from tests.conftest import FIXTURES

import pytest


def _codes(spec):
    return {issue.code for issue in spec.issues}


# ------------------------------------------------------------- OpenAPI 3.0


def test_v30_metadata_and_operations(load_fixture):
    spec = load_fixture("users_v3_0.yaml")
    assert spec.version is SpecVersion.OPENAPI_3_0
    assert (spec.title, spec.api_version) == ("Users API", "1.2.0")
    assert [s.url for s in spec.servers] == ["https://api.example.com/v1"]
    assert [op.key for op in spec.operations] == [
        "GET /health", "GET /users", "POST /users", "GET /users/{userId}", "DELETE /users/{userId}",
    ]
    assert set(spec.schema_names) == {"NewUser", "User", "Address"}


def test_v30_security_global_and_override(load_fixture):
    spec = load_fixture("users_v3_0.yaml")
    assert spec.global_security == [{"bearerAuth": []}]
    assert spec.find_operation("getHealth").security == []
    assert spec.find_operation("listUsers").security is None
    bearer = spec.security_schemes["bearerAuth"]
    assert (bearer.type, bearer.scheme, bearer.bearer_format) == ("http", "bearer", "JWT")


def test_v30_parameters_are_resolved_and_merged(load_fixture):
    spec = load_fixture("users_v3_0.yaml")
    get_user = spec.find_operation("GET /users/{userId}")
    (user_id,) = get_user.parameters
    assert (user_id.location, user_id.required, user_id.schema) == ("path", True, {"type": "integer"})
    assert user_id.pointer == "/components/parameters/UserId"

    (overridden,) = spec.find_operation("deleteUser").parameters
    assert overridden.schema["format"] == "uuid"

    locations = {(p.name, p.location, p.required) for p in spec.find_operation("listUsers").parameters}
    assert locations == {("limit", "query", False), ("X-Request-Id", "header", False)}


def test_v30_request_body_and_responses(load_fixture):
    spec = load_fixture("users_v3_0.yaml")
    create = spec.find_operation("createUser")
    assert create.request_body.required is True
    assert create.request_body.pointer == "/components/requestBodies/NewUser"
    (media,) = create.request_body.content
    assert media.content_type == "application/json"
    assert media.schema == {"$ref": "#/components/schemas/NewUser"}

    responses = {r.status_code: r for r in create.responses}
    assert set(responses) == {"201", "400", "401"}
    assert responses["201"].content[0].has_example
    assert responses["401"].description == "Token ausente ou inválido"


def test_v30_valid_spec_has_no_errors(load_fixture):
    spec = load_fixture("users_v3_0.yaml")
    assert not [issue for issue in spec.issues if issue.severity is Severity.ERROR]
    assert all(not ref.external and ref.resolved for ref in spec.references)


# ------------------------------------------------------------- OpenAPI 3.1


def test_v31_security_alternatives_and_cookie_parameter(load_fixture):
    spec = load_fixture("users_v3_1.json")
    assert spec.version is SpecVersion.OPENAPI_3_1
    operation = spec.find_operation("getUser")
    assert operation.security == [{"apiKey": []}, {"oauth": ["users:read"]}]
    assert {p.location for p in operation.parameters} == {"path", "cookie"}
    api_key = spec.security_schemes["apiKey"]
    assert (api_key.location, api_key.parameter_name) == ("header", "X-API-Key")
    assert "clientCredentials" in spec.security_schemes["oauth"].flows
    assert spec.servers[0].variables == {"env": {"default": "v2"}}
    assert "webhooks_ignored" in _codes(spec)


# ------------------------------------------------------------- Swagger 2.0


def test_v2_servers_and_security_schemes(load_fixture):
    spec = load_fixture("petstore_v2.yaml")
    assert spec.version is SpecVersion.SWAGGER_2_0
    assert [s.url for s in spec.servers] == ["https://petstore.example.com/api"]
    schemes = spec.security_schemes
    assert (schemes["basicAuth"].type, schemes["basicAuth"].scheme) == ("http", "basic")
    assert (schemes["apiKey"].location, schemes["apiKey"].parameter_name) == ("query", "api_key")
    assert schemes["petOauth"].flows["authorizationCode"]["scopes"] == {"write:pets": "altera pets"}
    assert set(spec.schema_names) == {"Pet"}


def test_v2_body_parameter_becomes_request_body(load_fixture):
    create = load_fixture("petstore_v2.yaml").find_operation("createPet")
    assert create.parameters == []
    assert create.request_body.required is True
    (media,) = create.request_body.content
    assert (media.content_type, media.schema) == ("application/json", {"$ref": "#/definitions/Pet"})
    assert create.security == [{"petOauth": ["write:pets"]}]


def test_v2_form_data_becomes_multipart_body(load_fixture):
    upload = load_fixture("petstore_v2.yaml").find_operation("uploadPhoto")
    (pet_id,) = upload.parameters
    assert pet_id.schema == {"type": "integer", "format": "int64"}
    (media,) = upload.request_body.content
    assert media.content_type == "multipart/form-data"
    assert media.schema["required"] == ["file"]
    assert set(media.schema["properties"]) == {"file", "caption"}


def test_v2_inline_query_schema_and_response_examples(load_fixture):
    list_pets = load_fixture("petstore_v2.yaml").find_operation("listPets")
    assert list_pets.parameters[0].schema == {"type": "integer", "maximum": 50}
    (media,) = list_pets.responses[0].content
    assert media.has_example and media.example == [{"id": 1, "name": "Rex"}]


# ------------------------------------------------------- incompleta/inválida


def test_incomplete_spec_reports_issues(load_fixture):
    spec = load_fixture("incomplete.yaml")
    codes = _codes(spec)
    assert {"missing_info_field", "external_ref", "broken_ref", "missing_responses",
            "undeclared_path_parameter", "invalid_operation", "default_server"} <= codes
    assert [op.key for op in spec.operations] == ["GET /orders/{orderId}", "POST /orders"]
    external = [ref for ref in spec.references if ref.external]
    assert [ref.ref for ref in external] == ["common.yaml#/components/schemas/Order"]


def test_find_operation_by_key_is_case_insensitive_on_method(load_fixture):
    spec = load_fixture("users_v3_0.yaml")
    assert spec.find_operation("get /users").operation_id == "listUsers"
    assert spec.find_operation("nope") is None


# ------------------------------------------------------------------- store


def test_spec_store_activates_last_loaded():
    store = SpecStore()
    with pytest.raises(SpecNotLoadedError):
        store.get()
    first_id, _ = store.load_file(FIXTURES / "users_v3_0.yaml")
    second_id, second = store.load_file(FIXTURES / "petstore_v2.yaml")
    assert store.get() is second
    assert store.get(first_id).title == "Users API"
    assert first_id.startswith("users_v3_0-") and second_id != first_id
