"""Ferramentas de planejamento de testes (os testes não são executados)."""

from __future__ import annotations

from typing import Any

from ..core.endpoint_analyzer import filter_operations
from ..core.test_planner import plan_operation_tests, plan_tests_for_operations
from ._common import active_spec, run_tool

_MAX_OPERATIONS = 10


def planejar_testes_endpoint(operacao: str, max_cenarios: int = 25) -> dict[str, Any]:
    """Planeja cenários de teste para uma operação a partir do contrato documentado.

    Args:
        operacao: operationId ou "METHOD /path".
        max_cenarios: Quantidade máxima de cenários retornados.
    """
    return run_tool(lambda: {"plan": plan_operation_tests(active_spec(), operacao, max_scenarios=max(1, max_cenarios))})


def planejar_testes_conjunto(
    operacoes: list[str] | None = None,
    tag: str | None = None,
    max_cenarios_por_operacao: int = 10,
) -> dict[str, Any]:
    """Planeja testes para várias operações (até 10), escolhidas pela lista ou por tag.

    Args:
        operacoes: Lista de operationIds ou "METHOD /path".
        tag: Tag cujas operações devem ser planejadas (usada se `operacoes` estiver vazia).
        max_cenarios_por_operacao: Limite de cenários por operação.
    """
    def action() -> dict[str, Any]:
        spec = active_spec()
        identifiers = operacoes or [op.key for op in filter_operations(spec, tag=tag)]
        if not identifiers:
            raise ValueError("Informe operações ou uma tag com operações.")
        selected = identifiers[:_MAX_OPERATIONS]
        result: dict[str, Any] = {
            "plans": plan_tests_for_operations(spec, selected, max_scenarios_per_operation=max(1, max_cenarios_por_operacao))
        }
        if len(identifiers) > len(selected):
            result["operations_omitted"] = identifiers[len(selected):]
        return result

    return run_tool(action)
