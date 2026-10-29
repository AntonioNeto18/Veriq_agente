"""Ferramenta de geração de collection Postman (as requisições não são executadas)."""

from __future__ import annotations

import json
from typing import Any

from ..core.postman_generator import CollectionOptions, collection_summary, generate_collection, write_collection
from ._common import active_spec, output_dir, run_tool

_MAX_INLINE_JSON = 60_000


def gerar_postman_collection(
    operacoes: list[str] | None = None,
    tag: str | None = None,
    metodo: str | None = None,
    autenticacao: str | None = None,
    texto: str | None = None,
    nome: str | None = None,
    incluir_cenarios: bool = False,
    salvar_arquivo: bool = True,
    retornar_json: bool = False,
) -> dict[str, Any]:
    """Gera e valida uma collection Postman v2.1.0 para o escopo solicitado. Não executa nenhuma requisição.

    Args:
        operacoes: operationIds ou "METHOD /path" a incluir. Sem valor, usa os filtros.
        tag: Inclui apenas operações com esta tag.
        metodo: Inclui apenas este método HTTP.
        autenticacao: "declared_required", "none_declared" ou "indeterminate".
        texto: Filtra por texto no path, operationId, summary, description ou tags.
        nome: Nome da collection (padrão: título da API).
        incluir_cenarios: Inclui pastas com os cenários de teste planejados.
        salvar_arquivo: Grava o JSON no diretório de saída.
        retornar_json: Inclui o JSON completo na resposta (use só quando o usuário pedir o JSON).
    """
    def action() -> dict[str, Any]:
        collection = generate_collection(
            active_spec(), operation_ids=operacoes or None, tag=tag, method=metodo, auth_status=autenticacao,
            text=texto, options=CollectionOptions(name=nome, include_scenarios=incluir_cenarios),
        )
        result: dict[str, Any] = {"validated": True, "executed": False, "summary": collection_summary(collection)}
        if salvar_arquivo:
            result["file"] = str(write_collection(collection, output_dir(), nome))
        if retornar_json:
            text = json.dumps(collection, ensure_ascii=False)
            if len(text) > _MAX_INLINE_JSON:
                hint = "use o arquivo salvo." if salvar_arquivo else "gere novamente com salvar_arquivo=true."
                result["json_omitted"] = f"Collection com {len(text)} caracteres excede o limite para resposta; {hint}"
            else:
                result["collection"] = collection
        return result

    return run_tool(action)
