"""Ferramentas expostas ao agente. Nenhuma delas executa requisições HTTP."""

from .endpoint_tools import listar_endpoints, obter_detalhes_endpoint
from .postman_tools import gerar_postman_collection
from .security_tools import analisar_autenticacao, listar_lacunas_autenticacao
from .specification_tools import (
    carregar_especificacao,
    listar_problemas_especificacao,
    listar_referencias,
    listar_schemas,
    obter_schema,
    resumo_especificacao,
)
from .test_planning_tools import planejar_testes_conjunto, planejar_testes_endpoint

ALL_TOOLS = [
    carregar_especificacao,
    resumo_especificacao,
    listar_problemas_especificacao,
    listar_schemas,
    obter_schema,
    listar_referencias,
    listar_endpoints,
    obter_detalhes_endpoint,
    analisar_autenticacao,
    listar_lacunas_autenticacao,
    planejar_testes_endpoint,
    planejar_testes_conjunto,
    gerar_postman_collection,
]

__all__ = ["ALL_TOOLS"] + [tool.__name__ for tool in ALL_TOOLS]
