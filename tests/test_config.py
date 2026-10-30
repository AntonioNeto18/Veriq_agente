from pathlib import Path

from agent_veriq import config

PACKAGE_DIR = Path(__file__).parent.parent / "agent_veriq"


def test_environment_defaults(monkeypatch, tmp_path):
    for name in (config.ENV_MODEL, config.ENV_SPEC_DIR, config.ENV_OUTPUT_DIR, config.ENV_MAX_SPEC_MB):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    assert config.model_name() is None
    assert config.spec_base_dir() == tmp_path.resolve()
    assert config.output_dir() == (tmp_path / config.DEFAULT_OUTPUT_DIRNAME).resolve()
    assert config.max_spec_bytes() == config.DEFAULT_MAX_SPEC_MB * 1024 * 1024


def test_environment_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv(config.ENV_MODEL, "outro-modelo")
    monkeypatch.setenv(config.ENV_SPEC_DIR, str(tmp_path / "specs"))
    monkeypatch.setenv(config.ENV_OUTPUT_DIR, str(tmp_path / "saida"))
    monkeypatch.setenv(config.ENV_MAX_SPEC_MB, "2")
    assert config.model_name() == "outro-modelo"
    assert config.spec_base_dir() == (tmp_path / "specs").resolve()
    assert config.output_dir() == (tmp_path / "saida").resolve()
    assert config.max_spec_bytes() == 2 * 1024 * 1024


def test_invalid_size_falls_back_to_default(monkeypatch):
    monkeypatch.setenv(config.ENV_MAX_SPEC_MB, "abc")
    assert config.max_spec_bytes() == config.DEFAULT_MAX_SPEC_MB * 1024 * 1024


def test_postman_schema_is_versioned_locally():
    assert config.POSTMAN_SCHEMA_PATH.is_file()


def test_only_config_reads_environment():
    offenders = [
        str(path.relative_to(PACKAGE_DIR)) for path in PACKAGE_DIR.rglob("*.py")
        if path.name != "config.py" and ("os.environ" in (text := path.read_text(encoding="utf-8"))
                                         or "getenv" in text)
    ]
    assert offenders == []
