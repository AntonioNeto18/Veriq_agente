"""Planejamento determinístico de cenários de teste a partir do contrato.

Os cenários são derivados apenas de restrições declaradas (obrigatoriedade,
tipos, formatos, limites, enums, content types, segurança e respostas
documentadas). Quando o status esperado não está documentado, o cenário é
marcado como hipótese. Nada aqui executa requisições.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..config import DEFAULT_MAX_SCENARIOS, DEFAULT_MAX_SCENARIOS_PER_OPERATION, MAX_INLINE_TEST_VALUE_SIZE
from .endpoint_analyzer import get_operation
from .models import ApiSpec, MediaType, Operation, Parameter
from .ref_resolver import RefResolver
from .schema_utils import DOCUMENTED, ExampleBuilder, normalized_type, object_view
from .security_analyzer import AuthStatus, analyze_operation_security

_VALIDATION_STATUSES = ("400", "422", "4XX")
_INVALID_FORMATS = {
    "email": "email-invalido",
    "uuid": "nao-e-um-uuid",
    "date": "31/13/2024",
    "date-time": "nao-e-uma-data",
    "uri": "nao e uma uri",
    "url": "nao e uma url",
    "ipv4": "999.999.999.999",
    "ipv6": "nao-e-ipv6",
}
_WRONG_TYPE_VALUES = {
    "string": 12345,
    "integer": "abc",
    "number": "abc",
    "boolean": "nao-booleano",
    "array": "nao-e-lista",
    "object": "nao-e-objeto",
}
_UNSUPPORTED_CONTENT_TYPE = "text/plain"
_NOTE_NOT_EXECUTED = "Cenários planejados a partir do contrato; nenhum foi executado."
_NOTE_BASIS = ("basis=documented: a restrição e o status esperado constam no contrato, mas a associação entre "
               "eles é inferida; basis=hypothesis: o status esperado não está documentado.")


class Basis(str, Enum):
    DOCUMENTED = "documented"  # restrição e status esperado estão na especificação
    HYPOTHESIS = "hypothesis"  # expectativa inferida, sem status documentado


@dataclass
class TestScenario:
    __test__ = False  # não é uma classe de teste do pytest

    id: str
    category: str
    description: str
    inputs: dict[str, Any]
    expected_status: list[str]
    basis: Basis
    source_pointer: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "category": self.category,
            "description": self.description,
            "inputs": self.inputs,
            "expected": {"status": self.expected_status or "não documentado"},
            "basis": self.basis.value,
            "source": self.source_pointer,
        }
        if self.notes:
            data["notes"] = self.notes
        return data


def plan_operation_tests(spec: ApiSpec, identifier: str, *, max_scenarios: int = DEFAULT_MAX_SCENARIOS) -> dict[str, Any]:
    """Plano de testes de uma operação: requisição válida de referência + cenários."""
    operation = get_operation(spec, identifier)
    planner = _OperationPlanner(spec, operation)
    scenarios = planner.build()
    plan: dict[str, Any] = {
        "operation": operation.key,
        "valid_request": planner.valid_request,
        "scenarios": [scenario.to_dict() for scenario in scenarios[:max_scenarios]],
        "notes": [_NOTE_NOT_EXECUTED, _NOTE_BASIS] + planner.notes,
    }
    if operation.operation_id:
        plan["operation_id"] = operation.operation_id
    if len(scenarios) > max_scenarios:
        plan["scenarios_omitted"] = len(scenarios) - max_scenarios
    return plan


def plan_tests_for_operations(
    spec: ApiSpec, identifiers: list[str], *, max_scenarios_per_operation: int = DEFAULT_MAX_SCENARIOS_PER_OPERATION
) -> list[dict[str, Any]]:
    return [plan_operation_tests(spec, identifier, max_scenarios=max_scenarios_per_operation)
            for identifier in identifiers]


class _OperationPlanner:
    def __init__(self, spec: ApiSpec, operation: Operation) -> None:
        self.spec = spec
        self.operation = operation
        self.resolver = RefResolver(spec.document)
        self.examples = ExampleBuilder(self.resolver)
        self.codes = [response.status_code for response in operation.responses]
        self.scenarios: list[TestScenario] = []
        self.notes: list[str] = []
        self.media = _primary_media(operation)
        self.valid_request = self._valid_request()

    # --------------------------------------------------------------- público

    def build(self) -> list[TestScenario]:
        self._positive_scenarios()
        self._authentication_scenarios()
        for parameter in self.operation.parameters:
            self._parameter_scenarios(parameter)
        self._body_scenarios()
        self._content_type_scenario()
        self._documented_response_scenarios()
        return self.scenarios

    # ---------------------------------------------------- requisição válida

    def _valid_request(self) -> dict[str, Any]:
        request: dict[str, Any] = {}
        origins: dict[str, str] = {}
        for parameter in self.operation.parameters:
            if not parameter.required:
                continue
            value, origin = self._parameter_value(parameter)
            request.setdefault(parameter.location, {})[parameter.name] = value
            origins[f"{parameter.location}.{parameter.name}"] = origin
        if self.media is not None:
            body, origin = self._media_example(self.media)
            request["content_type"] = self.media.content_type
            request["body"] = body
            origins["body"] = origin
        if origins:
            request["value_origins"] = origins
        return request

    def _parameter_value(self, parameter: Parameter) -> tuple[Any, str]:
        if parameter.has_example:
            return parameter.example, DOCUMENTED
        return self.examples.build(parameter.schema or {"type": "string"})

    def _media_example(self, media: MediaType) -> tuple[Any, str]:
        if media.has_example:
            return media.example, DOCUMENTED
        for item in media.examples.values():
            if isinstance(item, dict) and "value" in item:
                return item["value"], DOCUMENTED
        return self.examples.build(media.schema or {})

    # ------------------------------------------------------------- cenários

    def _add(self, category: str, description: str, inputs: dict[str, Any], expected: list[str],
             basis: Basis, pointer: str, notes: list[str] | None = None) -> None:
        prefix = self.operation.operation_id or _slug(self.operation.key)
        scenario_id = f"{prefix}-{len(self.scenarios) + 1:02d}"
        self.scenarios.append(TestScenario(scenario_id, category, description, inputs, expected, basis, pointer,
                                           notes or []))

    def _validation_expectation(self) -> tuple[list[str], Basis, list[str]]:
        documented = [code for code in self.codes if code in _VALIDATION_STATUSES]
        if documented:
            return documented, Basis.DOCUMENTED, []
        return [], Basis.HYPOTHESIS, ["A especificação não documenta resposta para entrada inválida; "
                                      "espera-se um 4xx (hipótese)."]

    def _positive_scenarios(self) -> None:
        success = [code for code in self.codes if code.startswith("2")]
        basis = Basis.DOCUMENTED if success else Basis.HYPOTHESIS
        notes = [] if success else ["Nenhuma resposta 2xx documentada."]
        self._add("positive", "Requisição válida com os dados de referência.", {"use": "valid_request"},
                  success, basis, self.operation.pointer, notes)
        optional = [p.name for p in self.operation.parameters if not p.required]
        if optional:
            self._add("positive", "Requisição válida incluindo parâmetros opcionais: " + ", ".join(optional) + ".",
                      {"use": "valid_request", "add_optional_parameters": optional}, success, basis,
                      self.operation.pointer, notes)

    def _authentication_scenarios(self) -> None:
        security = analyze_operation_security(self.spec, self.operation)
        if security.status is not AuthStatus.DECLARED_REQUIRED:
            if security.status is AuthStatus.INDETERMINATE:
                self.notes.append("Segurança indeterminada: cenários de autenticação não foram gerados.")
            return
        expected = ["401"] if "401" in self.codes else []
        basis = Basis.DOCUMENTED if expected else Basis.HYPOTHESIS
        notes = [] if expected else ["401 não documentado; status esperado é hipótese."]
        schemes = sorted({usage.name for alternative in security.alternatives for usage in alternative})
        self._add("authentication", "Requisição sem credenciais.", {"use": "valid_request", "auth": "omitted"},
                  expected, basis, security.pointer, notes)
        self._add("authentication", "Requisição com credencial inválida ou expirada.",
                  {"use": "valid_request", "auth": "invalid", "schemes": schemes}, expected, basis,
                  security.pointer, notes)
        scoped = [usage for alternative in security.alternatives for usage in alternative if usage.scopes]
        if scoped:
            forbidden = ["403"] if "403" in self.codes else []
            self._add("authorization", "Credencial válida sem os scopes exigidos: "
                      + ", ".join(sorted({scope for usage in scoped for scope in usage.scopes})) + ".",
                      {"use": "valid_request", "auth": "missing_scopes"}, forbidden,
                      Basis.DOCUMENTED if forbidden else Basis.HYPOTHESIS, security.pointer,
                      [] if forbidden else ["403 não documentado; status esperado é hipótese."])

    def _parameter_scenarios(self, parameter: Parameter) -> None:
        expected, basis, notes = self._validation_expectation()
        target = {"parameter": parameter.name, "in": parameter.location}
        label = f"{parameter.location} '{parameter.name}'"
        if parameter.required and parameter.location != "path":
            self._add("missing_required", f"Omitir o parâmetro obrigatório {label}.",
                      {**target, "action": "omit"}, expected, basis, parameter.pointer, notes)
        schema = self.resolver.inline(parameter.schema) if parameter.schema else {}
        for category, description, value in _invalid_values(schema):
            self._add(category, f"{label}: {description}.", {**target, "value": value}, expected, basis,
                      parameter.pointer, notes)
        if parameter.location == "path":
            not_found = ["404"] if "404" in self.codes else []
            if not_found:
                self._add("not_found", f"{label}: identificador válido de recurso inexistente.",
                          {**target, "value": "<id inexistente>"}, not_found, Basis.DOCUMENTED, parameter.pointer)

    def _body_scenarios(self) -> None:
        body = self.operation.request_body
        if body is None or self.media is None:
            return
        expected, basis, notes = self._validation_expectation()
        if body.required:
            self._add("missing_required", "Enviar a requisição sem body.", {"use": "valid_request", "body": None},
                      expected, basis, body.pointer, notes)
        schema = self.resolver.inline(self.media.schema) if self.media.schema else {}
        properties, required = object_view(schema)
        for name in required:
            self._add("missing_required", f"Body sem o campo obrigatório '{name}'.",
                      {"use": "valid_request", "body_remove": name}, expected, basis, body.pointer, notes)
        for name, field_schema in properties.items():
            if not isinstance(field_schema, dict) or field_schema.get("readOnly") is True:
                continue
            for category, description, value in _invalid_values(field_schema):
                self._add(category, f"Campo '{name}': {description}.",
                          {"use": "valid_request", "body_set": {name: value}}, expected, basis, body.pointer, notes)
            _, nullable = normalized_type(field_schema)
            if name in required and not nullable and "type" in field_schema:
                self._add("null_value", f"Campo obrigatório '{name}' com valor null (não declarado como nullable).",
                          {"use": "valid_request", "body_set": {name: None}}, expected, basis, body.pointer, notes)
        if any(isinstance(value, dict) and ("properties" in value or "items" in value) for value in properties.values()):
            self.notes.append("Campos aninhados não foram expandidos em cenários individuais.")

    def _content_type_scenario(self) -> None:
        body = self.operation.request_body
        if body is None or not body.content:
            return
        accepted = [media.content_type for media in body.content]
        if _UNSUPPORTED_CONTENT_TYPE in accepted or any(item in ("*/*", "text/*") for item in accepted):
            return
        expected = ["415"] if "415" in self.codes else []
        self._add("content_type", f"Enviar body com Content-Type não aceito ({_UNSUPPORTED_CONTENT_TYPE}).",
                  {"use": "valid_request", "content_type": _UNSUPPORTED_CONTENT_TYPE}, expected,
                  Basis.DOCUMENTED if expected else Basis.HYPOTHESIS, body.pointer,
                  [] if expected else ["415 não documentado; status esperado é hipótese. Aceitos: "
                                       + ", ".join(accepted) + "."])

    def _documented_response_scenarios(self) -> None:
        covered = {code for scenario in self.scenarios for code in scenario.expected_status}
        for response in self.operation.responses:
            if response.status_code in covered or response.status_code.startswith("2"):
                continue
            description = response.description or "sem descrição"
            self._add("documented_response", f"Provocar a resposta documentada {response.status_code}: {description}.",
                      {"use": "valid_request", "trigger": "condição não especificada no contrato"},
                      [response.status_code], Basis.DOCUMENTED, response.pointer,
                      ["A resposta está documentada, mas a condição que a provoca deve ser definida pelo usuário."])


# ------------------------------------------------------------------ helpers


def _primary_media(operation: Operation) -> MediaType | None:
    body = operation.request_body
    if body is None or not body.content:
        return None
    for media in body.content:
        if "json" in media.content_type:
            return media
    return body.content[0]


def _invalid_values(schema: dict[str, Any]) -> list[tuple[str, str, Any]]:
    """Valores inválidos derivados apenas das restrições declaradas no schema."""
    cases: list[tuple[str, str, Any]] = []
    schema_type, _ = normalized_type(schema)
    if isinstance(schema_type, str) and schema_type in _WRONG_TYPE_VALUES:
        cases.append(("invalid_type", f"tipo inválido (esperado {schema_type})", _WRONG_TYPE_VALUES[schema_type]))
    schema_format = schema.get("format")
    if schema_type == "string" and schema_format in _INVALID_FORMATS:
        cases.append(("invalid_format", f"formato inválido (esperado {schema_format})", _INVALID_FORMATS[schema_format]))
    if isinstance(schema.get("enum"), list) and schema["enum"]:
        cases.append(("invalid_enum", "valor fora do enum declarado", "__valor_fora_do_enum__"))
    cases.extend(_numeric_bounds(schema))
    cases.extend(_length_bounds(schema))
    if isinstance(schema.get("pattern"), str):
        cases.append(("invalid_pattern", f"valor que não atende ao pattern {schema['pattern']}", "!!!"))
    return cases


def _numeric_bounds(schema: dict[str, Any]) -> list[tuple[str, str, Any]]:
    cases = []
    step = 1 if schema.get("type") == "integer" else 0.01
    minimum, maximum = schema.get("minimum"), schema.get("maximum")
    exclusive_min, exclusive_max = schema.get("exclusiveMinimum"), schema.get("exclusiveMaximum")
    if _is_number(exclusive_min):
        cases.append(("out_of_range", f"valor igual ao exclusiveMinimum {exclusive_min}", exclusive_min))
    elif _is_number(minimum):
        value = minimum if exclusive_min is True else minimum - step
        cases.append(("out_of_range", f"valor abaixo do mínimo {minimum}", value))
    if _is_number(exclusive_max):
        cases.append(("out_of_range", f"valor igual ao exclusiveMaximum {exclusive_max}", exclusive_max))
    elif _is_number(maximum):
        value = maximum if exclusive_max is True else maximum + step
        cases.append(("out_of_range", f"valor acima do máximo {maximum}", value))
    return cases


def _length_bounds(schema: dict[str, Any]) -> list[tuple[str, str, Any]]:
    cases = []
    if schema.get("type") == "array":
        if isinstance(schema.get("minItems"), int) and schema["minItems"] > 0:
            cases.append(("length", f"lista com menos de {schema['minItems']} itens", []))
        if isinstance(schema.get("maxItems"), int):
            size = schema["maxItems"] + 1
            value = [f"<item {index}>" for index in range(size)] if size <= MAX_INLINE_TEST_VALUE_SIZE else \
                f"<lista com {size} itens>"
            cases.append(("length", f"lista com mais de {schema['maxItems']} itens", value))
        return cases
    if isinstance(schema.get("minLength"), int) and schema["minLength"] > 0:
        cases.append(("length", f"texto com menos de {schema['minLength']} caracteres",
                      _text_of_length(schema["minLength"] - 1)))
    if isinstance(schema.get("maxLength"), int):
        cases.append(("length", f"texto com mais de {schema['maxLength']} caracteres",
                      _text_of_length(schema["maxLength"] + 1)))
    return cases


def _text_of_length(size: int) -> str:
    """Texto literal quando curto; placeholder descritivo quando longo (economiza tokens)."""
    return "x" * size if size <= MAX_INLINE_TEST_VALUE_SIZE else f"<texto com {size} caracteres>"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
