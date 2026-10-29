import json

import pytest

from agent_veriq.core.spec_store import default_store
from agent_veriq.tools import (
    analisar_autenticacao,
    carregar_especificacao,
    gerar_postman_collection,
    listar_endpoints,
    listar_lacunas_autenticacao,
    listar_problemas_especificacao,
    listar_referencias,
    listar_schemas,
    obter_detalhes_endpoint,
    obter_schema,
    planejar_testes_conjunto,
    planejar_testes_endpoint,
    resumo_especificacao,
)
from tests.conftest import FIXTURES


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("VERIQ_SPEC_DIR", str(FIXTURES))
    monkeypatch.setenv("VERIQ_OUTPUT_DIR", str(tmp_path / "out"))
    default_store.clear()
    yield
    default_store.clear()


@pytest.fixture
def users():
    result = carregar_especificacao("users_v3_0.yaml")
    assert result["status"] == "ok", result
    return result


def test_tools_require_loaded_spec():
    result = listar_endpoints()
    assert result == {"status": "error", "error": "Nenhuma especificação carregada."}


def test_load_reports_overview(users):
    assert users["spec_version"] == "3.0.3"
    assert users["operations"] == 5
    assert users["security_schemes"] == ["bearerAuth"]
    assert users["spec_id"].startswith("users_v3_0-")


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("../../AGENTS.md", "Acesso negado"),
        ("../conftest.py", "Acesso negado"),
        ("nao_existe.yaml", "não encontrado"),
        ("invalid_syntax.yaml", "YAML inválido"),
    ],
)
def test_load_errors_are_structured(path, message):
    result = carregar_especificacao(path)
    assert result["status"] == "error" and message in result["error"]


def test_load_rejects_unsupported_extension(tmp_path, monkeypatch):
    monkeypatch.setenv("VERIQ_SPEC_DIR", str(tmp_path))
    (tmp_path / "spec.txt").write_text("openapi: 3.0.0", encoding="utf-8")
    assert "Extensão" in carregar_especificacao("spec.txt")["error"]


def test_specification_queries(users):
    assert resumo_especificacao()["tags"] == ["health", "users"]
    assert listar_schemas()["schemas"] == ["Address", "NewUser", "User"]
    schema = obter_schema("NewUser")
    assert schema["schema"]["required"] == ["name", "email"]
    assert obter_schema("Nope")["status"] == "error"
    assert listar_referencias()["total"] == 0
    assert listar_problemas_especificacao(severidade="error")["total"] == 0


def test_endpoint_tools(users):
    listed = listar_endpoints(tag="users", limite=2)
    assert len(listed["endpoints"]) == 2 and listed["omitted"] == 2
    details = obter_detalhes_endpoint("POST /users")["details"]
    assert details["operation_id"] == "createUser"
    assert obter_detalhes_endpoint("nope")["status"] == "error"
    assert listar_endpoints(autenticacao="publico")["status"] == "error"


def test_security_tools(users):
    overview = analisar_autenticacao()
    assert overview["operations_by_status"]["none_declared"] == 1
    health = next(row for row in overview["operations"] if row["operation"] == "GET /health")
    assert health["source"] == "operation_empty_override"
    single = analisar_autenticacao("createUser")
    assert single["security"]["status"] == "declared_required"
    assert "não foi verificado" in single["disclaimer"]
    gaps = listar_lacunas_autenticacao()
    assert {gap["code"] for gap in gaps["gaps"]} == {"auth_errors_not_documented"}


def test_planning_tools(users):
    plan = planejar_testes_endpoint("createUser", max_cenarios=5)["plan"]
    assert len(plan["scenarios"]) == 5
    grouped = planejar_testes_conjunto(tag="users", max_cenarios_por_operacao=2)
    assert [item["operation"] for item in grouped["plans"]] == [
        "GET /users", "POST /users", "GET /users/{userId}", "DELETE /users/{userId}"]
    assert planejar_testes_conjunto()["status"] == "ok"
    assert planejar_testes_conjunto(tag="nada")["status"] == "error"


def test_postman_tool_saves_and_returns_summary(users, tmp_path):
    result = gerar_postman_collection(autenticacao="none_declared", nome="Publicos")
    assert result["status"] == "ok" and result["validated"] and result["executed"] is False
    assert result["summary"]["requests"] == 1
    assert "collection" not in result
    saved = json.loads(open(result["file"], encoding="utf-8").read())
    assert saved["info"]["name"] == "Publicos"
    assert str(tmp_path / "out") in result["file"]


def test_postman_tool_returns_json_only_when_asked(users):
    result = gerar_postman_collection(operacoes=["createUser"], salvar_arquivo=False, retornar_json=True)
    assert "file" not in result
    assert result["collection"]["info"]["schema"].endswith("v2.1.0/collection.json")
    assert gerar_postman_collection(tag="inexistente")["status"] == "error"


def test_tool_results_are_json_serializable(users):
    for result in (resumo_especificacao(), listar_endpoints(), obter_detalhes_endpoint("createUser"),
                   analisar_autenticacao(), planejar_testes_endpoint("createUser")):
        json.dumps(result, ensure_ascii=False)
