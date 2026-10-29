import json

import pytest

from agent_veriq.core.endpoint_analyzer import (
    OperationNotFoundError,
    list_endpoints,
    missing_information,
    operation_details,
)
from agent_veriq.core.openapi_loader import load_spec_text
from agent_veriq.core.openapi_parser import parse_spec


@pytest.fixture
def spec(load_fixture):
    return load_fixture("users_v3_0.yaml")


def test_listing_is_minimal(spec):
    rows = list_endpoints(spec)
    assert len(rows) == 5
    assert rows[0] == {"method": "GET", "path": "/health", "auth": "none_declared", "operation_id": "getHealth",
                       "summary": "Verifica a saúde do serviço", "tags": ["health"]}
    assert all("parameters" not in row and "responses" not in row for row in rows)


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"tag": "USERS"}, ["listUsers", "createUser", "getUser", "deleteUser"]),
        ({"method": "post"}, ["createUser"]),
        ({"auth_status": "none_declared"}, ["getHealth"]),
        ({"text": "cadastra"}, ["createUser"]),
        ({"tag": "users", "method": "delete"}, ["deleteUser"]),
    ],
)
def test_listing_filters(spec, filters, expected):
    assert [row["operation_id"] for row in list_endpoints(spec, **filters)] == expected


def test_invalid_auth_filter_raises(spec):
    with pytest.raises(ValueError):
        list_endpoints(spec, auth_status="public")


def test_details_of_create_user(spec):
    details = operation_details(spec, "createUser")
    assert (details["method"], details["path"]) == ("POST", "/users")
    assert details["servers"] == ["https://api.example.com/v1"]
    body = details["request_body"]
    assert body["required"] is True
    schema = body["content"][0]["schema"]
    assert schema["ref"] == "NewUser"
    assert schema["required"] == ["name", "email"]
    assert schema["properties"]["email"] == {"type": "string", "format": "email"}
    assert schema["properties"]["address"]["ref"] == "Address"
    created = next(r for r in details["responses"] if r["status"] == "201")
    assert created["content"][0]["documented_examples"]["example"]["name"] == "Ana"
    assert details["security"]["status"] == "declared_required"
    assert "Request body sem exemplo documentado." in details["missing_information"]


def test_details_merge_all_of(spec):
    details = operation_details(spec, "GET /users/{userId}")
    user = details["responses"][0]["content"][0]["schema"]
    assert user["ref"] == "User"
    assert user["composed_of"] == ["NewUser"]
    assert set(user["properties"]) == {"name", "email", "address", "id"}
    assert set(user["required"]) == {"name", "email", "id"}


def test_details_unknown_operation(spec):
    with pytest.raises(OperationNotFoundError, match="não encontrada"):
        operation_details(spec, "GET /nope")


def test_details_report_issues_and_external_refs(load_fixture):
    spec = load_fixture("incomplete.yaml")
    details = operation_details(spec, "getOrder")
    schema = details["responses"][0]["content"][0]["schema"]
    assert schema["ref"] == "common.yaml#/components/schemas/Order"
    assert "externa" in schema["unresolved"]
    assert any(issue["code"] == "external_ref" for issue in details["issues"])
    assert details["security"]["status"] == "indeterminate"

    create = spec.find_operation("createOrder")
    assert "Nenhuma resposta documentada." in missing_information(create)


def test_details_circular_schema_is_marked(load_fixture):
    spec = load_fixture("incomplete.yaml")
    spec.document["paths"]["/orders"]["post"]["requestBody"]["content"]["application/json"]["schema"] = {
        "$ref": "#/components/schemas/Node"}
    reparsed = parse_spec(load_spec_text(json.dumps(spec.document), format_hint="json"))
    schema = operation_details(reparsed, "createOrder")["request_body"]["content"][0]["schema"]
    assert schema["properties"]["child"] == {"ref": "Node", "circular": True}


def test_details_are_json_serializable_and_compact(load_fixture):
    for name in ("users_v3_0.yaml", "users_v3_1.json", "petstore_v2.yaml", "security_mixed.yaml"):
        spec = load_fixture(name)
        for operation in spec.operations:
            payload = json.dumps(operation_details(spec, operation.key), ensure_ascii=False)
            assert len(payload) < 6000
