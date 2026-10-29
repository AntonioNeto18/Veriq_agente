"""Ferramentas de consulta de endpoints."""

from __future__ import annotations

from typing import Any

from ..core.endpoint_analyzer import list_endpoints, operation_details
from ._common import active_spec, limit_items, run_tool


def listar_endpoints(
    tag: str | None = None,
    metodo: str | None = None,
    autenticacao: str | None = None,
    texto: str | None = None,
    limite: int = 100,
) -> dict[str, Any]:
    """Lista endpoints da especificação ativa com campos mínimos (método, path, operationId, resumo, tags, auth).

    Args:
        tag: Filtra por tag (sem diferenciar maiúsculas).
        metodo: Filtra por método HTTP (ex.: "post").
        autenticacao: Filtra por "declared_required", "none_declared" ou "indeterminate".
        texto: Filtra por texto no path, operationId, summary, description ou tags.
        limite: Quantidade máxima de endpoints retornados.
    """
    def action() -> dict[str, Any]:
        rows = list_endpoints(active_spec(), tag=tag, method=metodo, auth_status=autenticacao, text=texto)
        return limit_items(rows, limite, "endpoints")

    return run_tool(action)


def obter_detalhes_endpoint(operacao: str) -> dict[str, Any]:
    """Retorna o contrato de uma operação: parâmetros, body, respostas, autenticação declarada e lacunas.

    Args:
        operacao: operationId ou "METHOD /path" (ex.: "POST /users").
    """
    return run_tool(lambda: {"details": operation_details(active_spec(), operacao)})
