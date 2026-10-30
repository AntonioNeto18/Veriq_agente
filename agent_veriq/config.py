"""Configuração central do agent-veriq.

Reúne as constantes ajustáveis (limites, caminhos, nomes e padrões) e a
leitura das variáveis de ambiente. As variáveis de ambiente são lidas a cada
chamada, para que mudanças no ambiente (e nos testes) tenham efeito imediato.

Tabelas de domínio — métodos HTTP, mapeamentos OpenAPI/Postman, expressões
regulares — permanecem nos módulos que as utilizam, pois descrevem os formatos
analisados e não a configuração do agente.
"""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent

# ----------------------------------------------------------- ambiente (.env)

ENV_MODEL = "VERIQ_MODEL"
ENV_SPEC_DIR = "VERIQ_SPEC_DIR"
ENV_OUTPUT_DIR = "VERIQ_OUTPUT_DIR"
ENV_MAX_SPEC_MB = "VERIQ_MAX_SPEC_MB"

DEFAULT_MAX_SPEC_MB = 10
DEFAULT_OUTPUT_DIRNAME = "output"


def model_name() -> str | None:
    """Modelo definido em `VERIQ_MODEL`; `None` usa o padrão do ADK."""
    return os.environ.get(ENV_MODEL) or None


def max_spec_bytes() -> int:
    """Limite de tamanho de especificações em bytes (`VERIQ_MAX_SPEC_MB`, padrão: 10 MB)."""
    raw = os.environ.get(ENV_MAX_SPEC_MB, "")
    try:
        megabytes = float(raw) if raw else DEFAULT_MAX_SPEC_MB
    except ValueError:
        megabytes = DEFAULT_MAX_SPEC_MB
    return int(max(megabytes, 0.001) * 1024 * 1024)


def spec_base_dir() -> Path:
    """Único diretório de onde especificações podem ser lidas (`VERIQ_SPEC_DIR`, padrão: diretório atual)."""
    return Path(os.environ.get(ENV_SPEC_DIR) or Path.cwd()).resolve()


def output_dir() -> Path:
    """Diretório onde collections são gravadas (`VERIQ_OUTPUT_DIR`, padrão: ./output)."""
    return Path(os.environ.get(ENV_OUTPUT_DIR) or Path.cwd() / DEFAULT_OUTPUT_DIRNAME).resolve()


# ------------------------------------------------- carregamento e parsing

ALLOWED_SPEC_SUFFIXES = (".json", ".yaml", ".yml")
MAX_YAML_ALIASES = 1_000
MAX_DOCUMENT_DEPTH = 256
MAX_DOCUMENT_NODES = 2_000_000
MAX_REF_HOPS = 32
REF_INLINE_MAX_DEPTH = 12

# ------------------------------------- tamanho do conteúdo enviado ao modelo

SCHEMA_SUMMARY_MAX_DEPTH = 4
SCHEMA_SUMMARY_MAX_DEPTH_LIMIT = 6
SCHEMA_SUMMARY_MAX_PROPERTIES = 40
MAX_DESCRIPTION_CHARS = 200
MAX_API_DESCRIPTION_CHARS = 500
MAX_INLINE_EXAMPLE_CHARS = 300
MAX_DOCUMENTED_EXAMPLES_CHARS = 1_200
MAX_EXAMPLES_PER_MEDIA = 2
EXAMPLE_BUILDER_MAX_DEPTH = 6

# ------------------------------------------------- planejamento de testes

DEFAULT_MAX_SCENARIOS = 40
DEFAULT_MAX_SCENARIOS_PER_OPERATION = 15
MAX_INLINE_TEST_VALUE_SIZE = 50
MAX_PLANNED_OPERATIONS = 10

# ------------------------------------------------------- collection Postman

POSTMAN_SCHEMA_URL = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
POSTMAN_SCHEMA_PATH = PACKAGE_DIR / "schemas" / "postman-collection-v2.1.0.schema.json"
BASE_URL_VARIABLE = "baseUrl"
# Valor fictício usado apenas em cenários de "credencial inválida"; não é um segredo.
INVALID_CREDENTIAL = "invalid-credential"
MAX_REPORTED_VALIDATION_ERRORS = 20
COLLECTION_PREVIEW_REQUESTS = 20
MAX_INLINE_COLLECTION_CHARS = 60_000

# ------------------------------------------------ padrões das ferramentas

TOOL_DEFAULT_LIST_LIMIT = 100
TOOL_DEFAULT_PROBLEMS_LIMIT = 30
TOOL_DEFAULT_REFERENCES_LIMIT = 50
TOOL_DEFAULT_GAPS_LIMIT = 50
TOOL_DEFAULT_SCHEMA_DEPTH = 3
TOOL_DEFAULT_SCENARIOS = 25
TOOL_DEFAULT_SCENARIOS_PER_OPERATION = 10
TOOL_LOAD_PROBLEMS_PREVIEW = 10

# ------------------------------------------------------------------ agente

AGENT_NAME = "veriq"
SKILLS_DIR = PACKAGE_DIR / "skills"
SKILL_NAMES = ("openapi-analysis", "endpoint-explanation", "api-test-planning", "postman-collection")
# Somente ferramentas de leitura de Skills; `run_skill_script` (execução de scripts) nunca é exposta.
SKILL_TOOL_ALLOWLIST = ["list_skills", "load_skill", "load_skill_resource"]
