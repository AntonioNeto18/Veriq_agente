"""Resumo compacto de schemas e geração de valores de exemplo sugeridos.

O resumo reduz o volume enviado ao modelo: limita profundidade e quantidade de
propriedades, mantém o nome dos schemas referenciados e sinaliza ciclos.
Valores de exemplo distinguem o que foi documentado (`documented`) do que foi
sugerido pelo próprio agente (`suggested`).
"""

from __future__ import annotations

import json
from typing import Any

from .ref_resolver import RefResolutionError, RefResolver

DOCUMENTED = "documented"
SUGGESTED = "suggested"

_CONSTRAINT_KEYS = (
    "format", "enum", "const", "default", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "multipleOf", "minLength", "maxLength", "pattern", "minItems", "maxItems", "uniqueItems",
    "minProperties", "maxProperties", "readOnly", "writeOnly", "deprecated",
)
_COMBINATORS = ("allOf", "oneOf", "anyOf")
_MAX_DESCRIPTION = 200
_MAX_INLINE_EXAMPLE = 300
_STRING_FORMAT_EXAMPLES = {
    "email": "user@example.com",
    "uuid": "123e4567-e89b-12d3-a456-426614174000",
    "date": "2024-01-31",
    "date-time": "2024-01-31T12:00:00Z",
    "time": "12:00:00",
    "uri": "https://example.com/resource",
    "url": "https://example.com/resource",
    "hostname": "example.com",
    "ipv4": "192.0.2.10",
    "ipv6": "2001:db8::10",
    "byte": "ZXhlbXBsbw==",
    "password": "<senha>",
}


def ref_name(ref: str) -> str:
    """Nome curto de um `$ref` interno (`#/components/schemas/User` → `User`)."""
    return ref.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~")


def compact_value(value: Any, limit: int = _MAX_INLINE_EXAMPLE) -> tuple[Any, bool]:
    """Retorna o valor se sua serialização couber no limite; senão `(None, True)`."""
    try:
        size = len(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return None, True
    return (value, False) if size <= limit else (None, True)


def normalized_type(schema: dict[str, Any]) -> tuple[str | list[str] | None, bool]:
    """Tipo do schema e se aceita null (cobre `nullable` do 3.0 e `type: [.., "null"]` do 3.1)."""
    raw = schema.get("type")
    nullable = schema.get("nullable") is True
    if isinstance(raw, list):
        non_null = [str(item) for item in raw if item != "null"]
        nullable = nullable or len(non_null) != len(raw)
        if len(non_null) == 1:
            return non_null[0], nullable
        return (non_null or None), nullable
    return (str(raw) if raw is not None else None), nullable


class SchemaSummarizer:
    def __init__(self, resolver: RefResolver, *, max_depth: int = 4, max_properties: int = 40) -> None:
        self.resolver = resolver
        self.max_depth = max_depth
        self.max_properties = max_properties

    def summarize(self, schema: Any) -> dict[str, Any] | None:
        if not isinstance(schema, dict):
            return None
        return self._walk(schema, 0, frozenset())

    def _walk(self, schema: Any, depth: int, active: frozenset[str]) -> dict[str, Any]:
        if not isinstance(schema, dict):
            return {}
        ref = schema.get("$ref")
        if isinstance(ref, str):
            return self._walk_ref(ref, depth, active)

        result: dict[str, Any] = {}
        schema_type, nullable = normalized_type(schema)
        if schema_type is not None:
            result["type"] = schema_type
        if nullable:
            result["nullable"] = True
        for key in _CONSTRAINT_KEYS:
            if key in schema:
                result[key] = schema[key]
        if isinstance(schema.get("description"), str):
            result["description"] = _truncate(schema["description"])
        if "example" in schema:
            example, omitted = compact_value(schema["example"])
            result["example_omitted" if omitted else "example"] = True if omitted else example
        if isinstance(schema.get("required"), list):
            result["required"] = list(schema["required"])
        if isinstance(schema.get("properties"), dict):
            self._add_properties(result, schema["properties"], depth, active)
        if isinstance(schema.get("items"), dict):
            result["items"] = self._walk(schema["items"], depth + 1, active)
        if isinstance(schema.get("additionalProperties"), (dict, bool)):
            extra = schema["additionalProperties"]
            result["additionalProperties"] = extra if isinstance(extra, bool) else self._walk(extra, depth + 1, active)
        if isinstance(schema.get("discriminator"), dict):
            result["discriminator"] = schema["discriminator"].get("propertyName")
        for combinator in _COMBINATORS:
            if isinstance(schema.get(combinator), list):
                parts = [self._walk(part, depth + 1, active) for part in schema[combinator]]
                if combinator == "allOf" and all(_is_mergeable(part) for part in parts):
                    _merge_all_of(result, parts)
                else:
                    result[combinator] = parts
        return result

    def _walk_ref(self, ref: str, depth: int, active: frozenset[str]) -> dict[str, Any]:
        name = ref_name(ref)
        if ref in active:
            return {"ref": name, "circular": True}
        if depth >= self.max_depth:
            return {"ref": name, "truncated": True}
        try:
            target = self.resolver.deref({"$ref": ref}).value
        except RefResolutionError as error:
            return {"ref": ref, "unresolved": error.reason}
        return {"ref": name, **self._walk(target, depth, active | {ref})}

    def _add_properties(self, result: dict[str, Any], properties: dict[str, Any], depth: int,
                        active: frozenset[str]) -> None:
        if depth >= self.max_depth:
            result["properties_omitted"] = len(properties)
            return
        selected = list(properties.items())[: self.max_properties]
        result["properties"] = {name: self._walk(value, depth + 1, active) for name, value in selected}
        if len(properties) > len(selected):
            result["properties_omitted"] = len(properties) - len(selected)


def _is_mergeable(part: dict[str, Any]) -> bool:
    return part.get("type", "object") == "object" and not any(key in part for key in _COMBINATORS)


def _merge_all_of(result: dict[str, Any], parts: list[dict[str, Any]]) -> None:
    result.setdefault("type", "object")
    names = [part["ref"] for part in parts if "ref" in part]
    if names:
        result["composed_of"] = names
    for part in parts:
        result.setdefault("properties", {}).update(part.get("properties", {}))
        for name in part.get("required", []):
            if name not in result.setdefault("required", []):
                result["required"].append(name)


def _truncate(text: str) -> str:
    return text if len(text) <= _MAX_DESCRIPTION else text[: _MAX_DESCRIPTION - 3] + "..."


class ExampleBuilder:
    """Gera um valor de exemplo para um schema, indicando se é documentado ou sugerido."""

    def __init__(self, resolver: RefResolver, *, max_depth: int = 6) -> None:
        self.resolver = resolver
        self.max_depth = max_depth

    def build(self, schema: Any, *, for_request: bool = True) -> tuple[Any, str]:
        if not isinstance(schema, dict):
            return None, SUGGESTED
        try:
            resolved = self.resolver.deref(schema).value
        except RefResolutionError:
            return None, SUGGESTED
        if isinstance(resolved, dict):
            if "example" in resolved:
                return resolved["example"], DOCUMENTED
            if isinstance(resolved.get("examples"), list) and resolved["examples"]:
                return resolved["examples"][0], DOCUMENTED
        return self._suggest(schema, 0, frozenset(), for_request), SUGGESTED

    def _suggest(self, schema: Any, depth: int, active: frozenset[str], for_request: bool) -> Any:
        if not isinstance(schema, dict) or depth > self.max_depth:
            return None
        ref = schema.get("$ref")
        if isinstance(ref, str):
            if ref in active:
                return None
            try:
                target = self.resolver.deref({"$ref": ref}).value
            except RefResolutionError:
                return None
            return self._suggest(target, depth, active | {ref}, for_request)
        for key in ("example", "default", "const"):
            if key in schema:
                return schema[key]
        if isinstance(schema.get("enum"), list) and schema["enum"]:
            return schema["enum"][0]
        if isinstance(schema.get("allOf"), list):
            merged: dict[str, Any] = {}
            for part in schema["allOf"]:
                value = self._suggest(part, depth + 1, active, for_request)
                if isinstance(value, dict):
                    merged.update(value)
            return merged
        for combinator in ("oneOf", "anyOf"):
            if isinstance(schema.get(combinator), list) and schema[combinator]:
                return self._suggest(schema[combinator][0], depth + 1, active, for_request)
        return self._suggest_by_type(schema, depth, active, for_request)

    def _suggest_by_type(self, schema: dict[str, Any], depth: int, active: frozenset[str], for_request: bool) -> Any:
        schema_type, _ = normalized_type(schema)
        if isinstance(schema_type, list):
            schema_type = schema_type[0]
        if schema_type is None:
            schema_type = "object" if "properties" in schema else "array" if "items" in schema else None
        if schema_type == "object":
            skipped = "readOnly" if for_request else "writeOnly"
            properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
            return {
                name: self._suggest(value, depth + 1, active, for_request)
                for name, value in properties.items()
                if not (isinstance(value, dict) and value.get(skipped) is True)
            }
        if schema_type == "array":
            return [self._suggest(schema.get("items"), depth + 1, active, for_request)]
        if schema_type == "string":
            return _suggest_string(schema)
        if schema_type in ("integer", "number"):
            return _suggest_number(schema, schema_type)
        if schema_type == "boolean":
            return True
        return None


def _suggest_string(schema: dict[str, Any]) -> str:
    value = _STRING_FORMAT_EXAMPLES.get(str(schema.get("format")), "string")
    min_length = schema.get("minLength")
    max_length = schema.get("maxLength")
    if isinstance(min_length, int) and len(value) < min_length:
        value = value + "x" * (min_length - len(value))
    if isinstance(max_length, int) and len(value) > max_length:
        value = value[:max_length]
    return value


def _suggest_number(schema: dict[str, Any], schema_type: str) -> int | float:
    step = 1 if schema_type == "integer" else 0.5
    minimum, maximum = schema.get("minimum"), schema.get("maximum")
    exclusive_min = schema.get("exclusiveMinimum")
    if isinstance(exclusive_min, (int, float)) and not isinstance(exclusive_min, bool):
        value = exclusive_min + step  # 3.1: exclusiveMinimum numérico
    elif isinstance(minimum, (int, float)):
        value = minimum + step if exclusive_min is True else minimum
    else:
        value = 1
    if isinstance(maximum, (int, float)) and value > maximum:
        value = maximum
    return int(value) if schema_type == "integer" else float(value)
