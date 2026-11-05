import json

import pytest

from agent_veriq.core.models import SpecVersion
from agent_veriq.core.openapi_loader import SpecLoadError, load_spec_file, load_spec_text
from tests.conftest import FIXTURES


@pytest.mark.parametrize(
    ("name", "version", "file_format"),
    [
        ("petstore_v2.yaml", SpecVersion.SWAGGER_2_0, "yaml"),
        ("users_v3_0.yaml", SpecVersion.OPENAPI_3_0, "yaml"),
        ("users_v3_1.json", SpecVersion.OPENAPI_3_1, "json"),
    ],
)
def test_detects_version_and_format(name, version, file_format):
    loaded = load_spec_file(FIXTURES / name)
    assert loaded.version is version
    assert loaded.format == file_format


def test_yaml_integer_status_codes_become_strings():
    loaded = load_spec_file(FIXTURES / "users_v3_0.yaml")
    assert "200" in loaded.document["paths"]["/health"]["get"]["responses"]


def test_yaml_dates_are_serializable():
    text = "openapi: 3.0.0\ninfo: {title: t, version: 1}\npaths: {}\nx-released: 2024-01-31\n"
    loaded = load_spec_text(text)
    assert loaded.document["x-released"] == "2024-01-31"
    json.dumps(loaded.document)


def test_invalid_yaml_reports_line():
    with pytest.raises(SpecLoadError) as error:
        load_spec_file(FIXTURES / "invalid_syntax.yaml")
    assert error.value.line is not None
    assert "Invalid YAML" in str(error.value)


def test_invalid_json_reports_line():
    with pytest.raises(SpecLoadError) as error:
        load_spec_text('{"openapi": "3.0.0",\n "info": }', format_hint="json")
    assert error.value.line == 2


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("info: {title: x}\n", "declares neither 'openapi' nor 'swagger'"),
        ("openapi: 4.0.0\n", "Unsupported"),
        ("swagger: '1.2'\n", "Unsupported"),
        ("- a\n- b\n", r"object \(map\)"),
        ("   \n", "Empty file"),
    ],
)
def test_rejects_non_openapi_documents(text, message):
    with pytest.raises(SpecLoadError, match=message):
        load_spec_text(text)


def test_rejects_file_over_size_limit():
    with pytest.raises(SpecLoadError, match="exceeds the"):
        load_spec_file(FIXTURES / "users_v3_0.yaml", max_bytes=100)


def test_size_limit_from_environment(monkeypatch):
    monkeypatch.setenv("VERIQ_MAX_SPEC_MB", "0.0001")
    with pytest.raises(SpecLoadError, match="exceeds the"):
        load_spec_file(FIXTURES / "users_v3_0.yaml")


def test_missing_file():
    with pytest.raises(SpecLoadError, match="not found"):
        load_spec_file(FIXTURES / "nao_existe.yaml")


def test_billion_laughs_is_rejected():
    lines = ["openapi: 3.0.0", "a0: &a0 [x, x, x, x, x, x, x, x, x]"]
    for level in range(1, 10):
        previous = f"*a{level - 1}"
        lines.append(f"a{level}: &a{level} [{', '.join([previous] * 9)}]")
    with pytest.raises(SpecLoadError, match="limit of .* nodes"):
        load_spec_text("\n".join(lines))


def test_yaml_does_not_construct_python_objects():
    with pytest.raises(SpecLoadError):
        load_spec_text("openapi: 3.0.0\nx: !!python/object/apply:os.system ['echo hi']\n")
