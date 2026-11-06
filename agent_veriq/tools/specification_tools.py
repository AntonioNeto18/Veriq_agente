"""Ferramentas de carga e visão geral da especificação."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import (
    ALLOWED_SPEC_SUFFIXES,
    MAX_API_DESCRIPTION_CHARS,
    SCHEMA_SUMMARY_MAX_DEPTH_LIMIT,
    TOOL_DEFAULT_LIST_LIMIT,
    TOOL_DEFAULT_PROBLEMS_LIMIT,
    TOOL_DEFAULT_REFERENCES_LIMIT,
    TOOL_DEFAULT_SCHEMA_DEPTH,
    TOOL_LOAD_PROBLEMS_PREVIEW,
    spec_base_dir,
)
from ..core.models import ApiSpec, Severity
from ..core.ref_resolver import RefResolver
from ..core.schema_utils import SchemaSummarizer
from ..core.spec_store import default_store
from ._common import active_spec, limit_items, run_tool


def carregar_especificacao(caminho: str) -> dict[str, Any]:
    """Carrega e valida um arquivo OpenAPI local (JSON ou YAML) e o torna a especificação ativa.

    Args:
        caminho: Caminho do arquivo, relativo ao diretório de especificações permitido.

    Returns:
        Identificador, versão, metadados, contagens e principais problemas encontrados.
    """
    def action() -> dict[str, Any]:
        spec_id, spec = default_store.load_file(_resolve_spec_path(caminho))
        return {"spec_id": spec_id, **_overview(spec),
                "problems": _problem_summary(spec, limit=TOOL_LOAD_PROBLEMS_PREVIEW)}

    return run_tool(action)


def resumo_especificacao() -> dict[str, Any]:
    """Resume a especificação ativa: versão, metadados, servidores, tags e contagens (sem detalhes de operações)."""
    return run_tool(lambda: _overview(active_spec()))


def listar_problemas_especificacao(severidade: str | None = None,
                                   limite: int = TOOL_DEFAULT_PROBLEMS_LIMIT) -> dict[str, Any]:
    """Lista erros, avisos e limitações detectados no parsing da especificação ativa.

    Args:
        severidade: Filtra por "error", "warning" ou "info". Sem valor, retorna todas.
        limite: Quantidade máxima de itens retornados.
    """
    def action() -> dict[str, Any]:
        wanted = Severity(severidade) if severidade else None
        issues = [issue.to_dict() for issue in active_spec().issues if wanted is None or issue.severity is wanted]
        return limit_items(issues, limite, "problems")

    return run_tool(action)


def listar_schemas(limite: int = TOOL_DEFAULT_LIST_LIMIT) -> dict[str, Any]:
    """Lista os nomes dos schemas reutilizáveis (components.schemas ou definitions) da especificação ativa."""
    return run_tool(lambda: limit_items(sorted(active_spec().schema_names), limite, "schemas"))


def obter_schema(nome: str, profundidade: int = TOOL_DEFAULT_SCHEMA_DEPTH) -> dict[str, Any]:
    """Retorna o resumo estruturado de um schema reutilizável.

    Args:
        nome: Nome do schema (ex.: "User").
        profundidade: Níveis de aninhamento expandidos (mínimo 1; valores altos são limitados).
    """
    def action() -> dict[str, Any]:
        spec = active_spec()
        if nome not in spec.schema_names:
            raise ValueError(f"Schema '{nome}' not found. Use listar_schemas to see the available names.")
        pointer = spec.schema_names[nome]
        depth = min(max(profundidade, 1), SCHEMA_SUMMARY_MAX_DEPTH_LIMIT)
        summarizer = SchemaSummarizer(RefResolver(spec.document), max_depth=depth)
        return {"name": nome, "pointer": pointer, "schema": summarizer.summarize({"$ref": f"#{pointer}"})}

    return run_tool(action)


def listar_referencias(apenas_problemas: bool = True,
                       limite: int = TOOL_DEFAULT_REFERENCES_LIMIT) -> dict[str, Any]:
    """Lista referências `$ref` da especificação; por padrão apenas externas ou não resolvidas.

    Referências externas nunca são acessadas pelo agente.

    Args:
        apenas_problemas: Se verdadeiro, retorna só referências externas ou quebradas.
        limite: Quantidade máxima de itens retornados.
    """
    def action() -> dict[str, Any]:
        references = [
            {"ref": ref.ref, "pointer": ref.pointer, "external": ref.external, "resolved": ref.resolved}
            for ref in active_spec().references if not apenas_problemas or ref.external or not ref.resolved
        ]
        return limit_items(references, limite, "references")

    return run_tool(action)


# ------------------------------------------------------------------ helpers


def _resolve_spec_path(caminho: str) -> Path:
    base = spec_base_dir()
    candidate = Path(caminho)
    path = (candidate if candidate.is_absolute() else base / candidate).resolve()
    if not path.is_relative_to(base):
        raise PermissionError(f"Access denied: the file must be inside {base}.")
    if path.suffix.lower() not in ALLOWED_SPEC_SUFFIXES:
        raise ValueError(f"Unsupported extension; use {', '.join(ALLOWED_SPEC_SUFFIXES)}.")
    return path


def _overview(spec: ApiSpec) -> dict[str, Any]:
    counts = {severity.value: 0 for severity in Severity}
    for issue in spec.issues:
        counts[issue.severity.value] += 1
    data: dict[str, Any] = {
        "source": spec.source_name,
        "spec_version": spec.version_string,
        "format_family": "Swagger" if spec.version.value == "2.0" else "OpenAPI",
        "title": spec.title,
        "api_version": spec.api_version,
        "servers": [server.url for server in spec.servers],
        "tags": sorted({tag for operation in spec.operations for tag in operation.tags}),
        "operations": len(spec.operations),
        "schemas": len(spec.schema_names),
        "security_schemes": sorted(spec.security_schemes),
        "problem_counts": counts,
    }
    if spec.description:
        data["description"] = spec.description[:MAX_API_DESCRIPTION_CHARS]
    return data


def _problem_summary(spec: ApiSpec, limit: int) -> list[dict[str, str]]:
    relevant = [issue.to_dict() for issue in spec.issues if issue.severity is not Severity.INFO]
    return relevant[:limit]
