"""Validação local de collections Postman v2.1.0.

Usa o schema oficial versionado em `agent_veriq/schemas/` (sem acesso à rede)
e verificações adicionais do projeto: JSON serializável e ausência de valores
de credencial que não sejam variáveis `{{...}}`.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft4Validator

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "postman-collection-v2.1.0.schema.json"
_VARIABLE = re.compile(r"^\{\{[A-Za-z0-9_.-]+\}\}$")
_CREDENTIAL_KEYS = {"token", "password", "value", "accessToken", "clientSecret"}
_MAX_REPORTED_ERRORS = 20
# Valor fictício usado apenas em cenários de "credencial inválida"; não é um segredo.
INVALID_CREDENTIAL = "invalid-credential"


@lru_cache(maxsize=1)
def _validator() -> Draft4Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft4Validator(schema)


def validate_collection(collection: dict[str, Any]) -> list[str]:
    """Retorna a lista de problemas encontrados (vazia quando a collection é válida)."""
    try:
        json.loads(json.dumps(collection, ensure_ascii=False))
    except (TypeError, ValueError) as error:
        return [f"Collection não é JSON serializável: {error}"]
    errors = [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<raiz>'}: {error.message}"
        for error in sorted(_validator().iter_errors(collection), key=lambda item: list(item.absolute_path))
    ][:_MAX_REPORTED_ERRORS]
    errors.extend(_credential_problems(collection))
    return errors


def _credential_problems(collection: dict[str, Any]) -> list[str]:
    """Garante que atributos de credencial em `auth` só contenham variáveis de ambiente."""
    problems = []
    for auth, location in _iter_auth(collection, "collection"):
        auth_type = auth.get("type")
        attributes = auth.get(auth_type) if isinstance(auth_type, str) else None
        if not isinstance(attributes, list):
            continue
        for attribute in attributes:
            if not isinstance(attribute, dict) or attribute.get("key") not in _CREDENTIAL_KEYS:
                continue
            if auth_type == "apikey" and attribute.get("key") != "value":
                continue
            value = attribute.get("value")
            if isinstance(value, str) and value and not _VARIABLE.match(value) and value != INVALID_CREDENTIAL:
                problems.append(f"{location}: credencial '{attribute['key']}' deve ser uma variável {{{{...}}}}.")
    return problems


def _iter_auth(node: Any, location: str):
    if isinstance(node, dict):
        if isinstance(node.get("auth"), dict):
            yield node["auth"], location
        name = node.get("name", location)
        for key in ("item", "request"):
            child = node.get(key)
            if isinstance(child, list):
                for item in child:
                    yield from _iter_auth(item, str(item.get("name", name)) if isinstance(item, dict) else name)
            elif isinstance(child, dict):
                yield from _iter_auth(child, name)
