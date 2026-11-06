import json

import pytest

from agent_veriq.core.endpoint_analyzer import OperationNotFoundError
from agent_veriq.core.openapi_loader import load_spec_text
from agent_veriq.core.openapi_parser import parse_spec
from agent_veriq.core.test_planner import plan_operation_tests, plan_tests_for_operations


def _by_category(plan):
    grouped = {}
    for scenario in plan["scenarios"]:
        grouped.setdefault(scenario["category"], []).append(scenario)
    return grouped


@pytest.fixture
def users(load_fixture):
    return load_fixture("users_v3_0.yaml")


def test_plan_structure_and_ids(users):
    plan = plan_operation_tests(users, "createUser")
    assert plan["operation"] == "POST /users"
    ids = [scenario["id"] for scenario in plan["scenarios"]]
    assert ids[0] == "createUser-01" and len(ids) == len(set(ids))
    for scenario in plan["scenarios"]:
        assert {"id", "category", "description", "inputs", "expected", "basis", "source"} <= set(scenario)
        assert scenario["basis"] in ("documented", "hypothesis")
    assert any("none was executed" in note for note in plan["notes"])


def test_valid_request_marks_value_origin(users):
    plan = plan_operation_tests(users, "createUser")
    request = plan["valid_request"]
    assert request["content_type"] == "application/json"
    assert set(request["body"]) >= {"name", "email"}
    assert request["value_origins"] == {"body": "suggested"}


def test_body_scenarios_come_from_contract(users):
    grouped = _by_category(plan_operation_tests(users, "createUser"))
    removed = {s["inputs"].get("body_remove") for s in grouped["missing_required"]}
    assert {"name", "email"} <= removed
    assert grouped["invalid_format"][0]["inputs"]["body_set"] == {"email": "invalid-email"}
    lengths = [s["inputs"]["body_set"]["name"] for s in grouped["length"]]
    assert lengths == ["", "<text with 81 characters>"]
    assert all(s["expected"]["status"] == ["400"] and s["basis"] == "documented" for s in grouped["length"])


def test_authentication_scenarios_only_when_declared(users):
    create = _by_category(plan_operation_tests(users, "createUser"))
    assert [s["expected"]["status"] for s in create["authentication"]] == [["401"], ["401"]]
    health = _by_category(plan_operation_tests(users, "getHealth"))
    assert "authentication" not in health


def test_undocumented_status_is_hypothesis(users):
    grouped = _by_category(plan_operation_tests(users, "createUser"))
    (content_type,) = grouped["content_type"]
    assert content_type["basis"] == "hypothesis"
    assert content_type["expected"]["status"] == "not documented"

    get_user = _by_category(plan_operation_tests(users, "getUser"))
    assert all(s["basis"] == "hypothesis" for s in get_user["authentication"])


def test_path_and_query_parameters(users):
    get_user = _by_category(plan_operation_tests(users, "getUser"))
    assert get_user["invalid_type"][0]["inputs"] == {"parameter": "userId", "in": "path", "value": "abc"}
    assert get_user["not_found"][0]["expected"]["status"] == ["404"]

    list_users = _by_category(plan_operation_tests(users, "listUsers"))
    bounds = [s["inputs"]["value"] for s in list_users["out_of_range"]]
    assert bounds == [0, 101]
    assert list_users["positive"][1]["inputs"]["add_optional_parameters"] == ["limit", "X-Request-Id"]


def test_documented_responses_not_otherwise_covered(load_fixture):
    spec = parse_spec(load_spec_text("""
openapi: 3.0.0
info: {title: t, version: '1'}
paths:
  /items:
    post:
      operationId: createItem
      responses:
        '201': {description: criado}
        '409': {description: item duplicado}
"""))
    grouped = _by_category(plan_operation_tests(spec, "createItem"))
    (conflict,) = grouped["documented_response"]
    assert conflict["expected"]["status"] == ["409"]
    assert "item duplicado" in conflict["description"]
    assert conflict["inputs"]["trigger"] == "condition not specified in the contract"


def test_security_scopes_and_indeterminate(load_fixture):
    spec = load_fixture("security_mixed.yaml")
    alternatives = _by_category(plan_operation_tests(spec, "alternativesOp"))
    assert alternatives["authorization"][0]["basis"] == "hypothesis"
    unknown = plan_operation_tests(spec, "unknownOp")
    assert "authentication" not in _by_category(unknown)
    assert any("indeterminate" in note.lower() for note in unknown["notes"])


def test_swagger2_form_and_parameters(load_fixture):
    spec = load_fixture("petstore_v2.yaml")
    plan = plan_operation_tests(spec, "uploadPhoto")
    assert plan["valid_request"]["content_type"] == "multipart/form-data"
    assert plan["valid_request"]["path"] == {"petId": 1}
    removed = {s["inputs"].get("body_remove") for s in _by_category(plan)["missing_required"]}
    assert "file" in removed


def test_long_limits_use_placeholders():
    spec = parse_spec(load_spec_text("""
openapi: 3.0.0
info: {title: t, version: '1'}
paths:
  /notes:
    post:
      operationId: createNote
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                text: {type: string, maxLength: 5000}
      responses:
        '201': {description: ok}
"""))
    (length,) = _by_category(plan_operation_tests(spec, "createNote"))["length"]
    assert length["inputs"]["body_set"]["text"] == "<text with 5001 characters>"


def test_max_scenarios_and_multiple_operations(users):
    plan = plan_operation_tests(users, "createUser", max_scenarios=3)
    assert len(plan["scenarios"]) == 3 and plan["scenarios_omitted"] > 0
    plans = plan_tests_for_operations(users, ["getHealth", "deleteUser"], max_scenarios_per_operation=5)
    assert [item["operation"] for item in plans] == ["GET /health", "DELETE /users/{userId}"]
    with pytest.raises(OperationNotFoundError):
        plan_operation_tests(users, "nope")


def test_plans_are_serializable_for_all_fixtures(load_fixture):
    for name in ("users_v3_0.yaml", "users_v3_1.json", "petstore_v2.yaml", "security_mixed.yaml", "incomplete.yaml"):
        spec = load_fixture(name)
        for operation in spec.operations:
            json.dumps(plan_operation_tests(spec, operation.key), ensure_ascii=False)
