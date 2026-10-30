"""Ferramentas de análise da autenticação declarada."""

from __future__ import annotations

from typing import Any

from ..config import TOOL_DEFAULT_GAPS_LIMIT, TOOL_DEFAULT_LIST_LIMIT
from ..core.endpoint_analyzer import get_operation
from ..core.security_analyzer import (
    DISCLAIMER,
    analyze_all_operations,
    analyze_operation_security,
    find_security_gaps,
    security_overview,
)
from ._common import active_spec, limit_items, run_tool


def analisar_autenticacao(operacao: str | None = None, limite: int = TOOL_DEFAULT_LIST_LIMIT) -> dict[str, Any]:
    """Analisa os requisitos de autenticação DECLARADOS (não verifica o servidor real).

    Args:
        operacao: operationId ou "METHOD /path". Sem valor, retorna a visão geral e a situação de cada operação.
        limite: Quantidade máxima de operações na visão geral.
    """
    def action() -> dict[str, Any]:
        spec = active_spec()
        if operacao:
            result = analyze_operation_security(spec, get_operation(spec, operacao))
            return {"disclaimer": DISCLAIMER, "security": result.to_dict()}
        rows = [_compact(result.to_dict()) for result in analyze_all_operations(spec)]
        return {**security_overview(spec), **limit_items(rows, limite, "operations")}

    return run_tool(action)


def listar_lacunas_autenticacao(limite: int = TOOL_DEFAULT_GAPS_LIMIT) -> dict[str, Any]:
    """Lista informações de autenticação ausentes, inconsistentes ou não interpretáveis na especificação."""
    def action() -> dict[str, Any]:
        gaps = [gap.to_dict() for gap in find_security_gaps(active_spec())]
        return {"disclaimer": DISCLAIMER, **limit_items(gaps, limite, "gaps")}

    return run_tool(action)


def _compact(data: dict[str, Any]) -> dict[str, Any]:
    """Na visão geral, troca o detalhe das alternativas pelos nomes dos esquemas."""
    alternatives = data.pop("alternatives", None)
    if alternatives:
        data["schemes"] = [" + ".join(usage["scheme"] for usage in alternative) for alternative in alternatives]
    data.pop("pointer", None)
    return data
