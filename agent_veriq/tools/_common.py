"""Utilitários compartilhados pelas ferramentas expostas ao agente.

Toda ferramenta retorna um `dict` com `status` ("ok" ou "error"). Erros
esperados viram mensagens para o modelo em vez de exceções.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..core.endpoint_analyzer import OperationNotFoundError
from ..core.models import ApiSpec
from ..core.openapi_loader import SpecLoadError
from ..core.postman_generator import CollectionGenerationError
from ..core.spec_store import SpecNotLoadedError, default_store

_EXPECTED_ERRORS = (SpecLoadError, SpecNotLoadedError, OperationNotFoundError, CollectionGenerationError,
                    ValueError, PermissionError)


def run_tool(action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Executa a ação e converte erros esperados em resposta estruturada."""
    try:
        return {"status": "ok", **action()}
    except _EXPECTED_ERRORS as error:
        return {"status": "error", "error": str(error)}


def active_spec() -> ApiSpec:
    return default_store.get()


def limit_items(items: list[Any], limit: int, key: str) -> dict[str, Any]:
    """Limita listas longas e informa quantos itens foram omitidos."""
    limit = max(1, limit)
    result: dict[str, Any] = {key: items[:limit], "total": len(items)}
    if len(items) > limit:
        result["omitted"] = len(items) - limit
    return result


def spec_base_dir() -> Path:
    """Diretório a partir do qual arquivos OpenAPI podem ser lidos (`VERIQ_SPEC_DIR`, padrão: diretório atual)."""
    return Path(os.environ.get("VERIQ_SPEC_DIR") or Path.cwd()).resolve()


def output_dir() -> Path:
    """Diretório onde collections são gravadas (`VERIQ_OUTPUT_DIR`, padrão: ./output)."""
    return Path(os.environ.get("VERIQ_OUTPUT_DIR") or Path.cwd() / "output").resolve()
