"""Resolução de referências `$ref` internas.

Somente referências internas (`#/...`) são resolvidas. Referências externas
(arquivos ou URLs) nunca são acessadas: ficam registradas como não resolvidas
para que o agente possa informar essa limitação.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from ..config import MAX_REF_HOPS, REF_INLINE_MAX_DEPTH
from .models import Reference

CIRCULAR_MARKER = "x-veriq-circular"
UNRESOLVED_MARKER = "x-veriq-unresolved"


class RefResolutionError(Exception):
    """Referência que não pôde ser resolvida com segurança."""

    def __init__(self, ref: str, reason: str) -> None:
        super().__init__(f"Não foi possível resolver '{ref}': {reason}")
        self.ref = ref
        self.reason = reason


@dataclass(frozen=True)
class Resolved:
    value: Any
    pointer: str  # JSON Pointer do valor final dentro do documento
    ref_chain: tuple[str, ...] = ()


def is_external_ref(ref: str) -> bool:
    return not ref.startswith("#")


def escape_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def join_pointer(base: str, *tokens: str | int) -> str:
    return base + "".join(f"/{escape_pointer_token(str(token))}" for token in tokens)


class RefResolver:
    def __init__(self, document: dict[str, Any]) -> None:
        self._document = document

    def resolve_pointer(self, pointer: str) -> Any:
        """Retorna o valor apontado por um JSON Pointer (`/components/schemas/User`)."""
        if pointer in ("", "#"):
            return self._document
        if not pointer.startswith("/"):
            raise RefResolutionError(pointer, "JSON Pointer deve começar com '/'")
        current: Any = self._document
        for raw_token in pointer[1:].split("/"):
            token = unquote(raw_token).replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict) and token in current:
                current = current[token]
            elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
                current = current[int(token)]
            else:
                raise RefResolutionError(pointer, f"o caminho '{token}' não existe no documento")
        return current

    def deref(self, node: Any, pointer: str = "") -> Resolved:
        """Segue cadeias de `$ref` até um valor concreto.

        Lança `RefResolutionError` para referências externas, inexistentes ou circulares.
        """
        chain: list[str] = []
        current, current_pointer = node, pointer
        while isinstance(current, dict) and isinstance(current.get("$ref"), str):
            ref = current["$ref"]
            if is_external_ref(ref):
                raise RefResolutionError(ref, "referência externa não é acessada automaticamente")
            if ref in chain:
                raise RefResolutionError(ref, "referência circular")
            if len(chain) >= MAX_REF_HOPS:
                raise RefResolutionError(ref, f"cadeia com mais de {MAX_REF_HOPS} referências")
            chain.append(ref)
            current_pointer = ref[1:]
            current = self.resolve_pointer(current_pointer)
        return Resolved(current, current_pointer, tuple(chain))

    def inline(self, node: Any, max_depth: int = REF_INLINE_MAX_DEPTH) -> Any:
        """Expande `$ref` internos de um schema, cortando ciclos e profundidade excessiva.

        Ciclos são substituídos por `{"$ref": ..., "x-veriq-circular": true}` e
        referências não resolvíveis por `{"$ref": ..., "x-veriq-unresolved": motivo}`.
        """

        def walk(value: Any, active: tuple[str, ...], depth: int) -> Any:
            if isinstance(value, list):
                return [walk(item, active, depth) for item in value]
            if not isinstance(value, dict):
                return value
            ref = value.get("$ref")
            if isinstance(ref, str):
                if ref in active or depth >= max_depth:
                    return {"$ref": ref, CIRCULAR_MARKER: True}
                try:
                    target = self.deref({"$ref": ref}).value
                except RefResolutionError as error:
                    return {"$ref": ref, UNRESOLVED_MARKER: error.reason}
                siblings = {key: item for key, item in value.items() if key != "$ref"}
                expanded = walk(target, active + (ref,), depth + 1)
                if siblings and isinstance(expanded, dict):
                    expanded = {**expanded, **walk(siblings, active, depth)}
                return expanded
            return {key: walk(item, active, depth) for key, item in value.items()}

        return walk(node, (), 0)

    def collect_references(self) -> list[Reference]:
        """Enumera todas as ocorrências de `$ref` com sua localização e estado de resolução."""
        found: list[Reference] = []
        stack: list[tuple[Any, str]] = [(self._document, "")]
        while stack:
            value, pointer = stack.pop()
            if isinstance(value, dict):
                ref = value.get("$ref")
                if isinstance(ref, str):
                    found.append(self._describe(ref, join_pointer(pointer, "$ref")))
                for key, item in value.items():
                    if key != "$ref":
                        stack.append((item, join_pointer(pointer, key)))
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    stack.append((item, join_pointer(pointer, index)))
        return sorted(found, key=lambda reference: reference.pointer)

    def _describe(self, ref: str, pointer: str) -> Reference:
        if is_external_ref(ref):
            return Reference(ref=ref, pointer=pointer, external=True, resolved=False)
        try:
            self.resolve_pointer(ref[1:])
            resolved = True
        except RefResolutionError:
            resolved = False
        return Reference(ref=ref, pointer=pointer, external=False, resolved=resolved)
