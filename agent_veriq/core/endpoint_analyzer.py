"""Listagem enxuta de endpoints e detalhamento de uma operação.

A listagem retorna só os campos necessários para escolher uma operação; o
detalhamento resume schemas e exemplos para limitar o volume de contexto.
"""

from __future__ import annotations

from typing import Any

from ..config import MAX_DOCUMENTED_EXAMPLES_CHARS, MAX_EXAMPLES_PER_MEDIA, SCHEMA_SUMMARY_MAX_DEPTH
from .models import ApiSpec, MediaType, Operation, Parameter, RequestBody, Response, Severity
from .ref_resolver import RefResolver
from .schema_utils import SchemaSummarizer, compact_value
from .security_analyzer import AuthStatus, analyze_operation_security


class OperationNotFoundError(LookupError):
    """Operação inexistente na especificação ativa."""


def list_endpoints(
    spec: ApiSpec,
    *,
    tag: str | None = None,
    method: str | None = None,
    auth_status: str | None = None,
    text: str | None = None,
) -> list[dict[str, Any]]:
    """Lista operações com campos mínimos, aplicando filtros opcionais."""
    selected = filter_operations(spec, tag=tag, method=method, auth_status=auth_status, text=text)
    return [_endpoint_row(operation, analyze_operation_security(spec, operation).status) for operation in selected]


def filter_operations(
    spec: ApiSpec,
    *,
    tag: str | None = None,
    method: str | None = None,
    auth_status: str | None = None,
    text: str | None = None,
) -> list[Operation]:
    """Operações que atendem a todos os filtros informados (AND)."""
    wanted_status = AuthStatus(auth_status) if auth_status else None
    needle = text.lower() if text else None
    selected = []
    for operation in spec.operations:
        if tag and tag.lower() not in (item.lower() for item in operation.tags):
            continue
        if method and operation.method != method.lower():
            continue
        if wanted_status and analyze_operation_security(spec, operation).status is not wanted_status:
            continue
        if needle and needle not in _searchable_text(operation):
            continue
        selected.append(operation)
    return selected


def get_operation(spec: ApiSpec, identifier: str) -> Operation:
    operation = spec.find_operation(identifier)
    if operation is None:
        raise OperationNotFoundError(
            f"Operação '{identifier}' não encontrada. Use o operationId ou o formato 'METHOD /path'."
        )
    return operation


def operation_details(spec: ApiSpec, identifier: str, *,
                      max_schema_depth: int = SCHEMA_SUMMARY_MAX_DEPTH) -> dict[str, Any]:
    """Contrato de uma operação: parâmetros, body, respostas, segurança e lacunas."""
    operation = get_operation(spec, identifier)
    summarizer = SchemaSummarizer(RefResolver(spec.document), max_depth=max_schema_depth)
    details: dict[str, Any] = {
        "operation": operation.key,
        "method": operation.method.upper(),
        "path": operation.path,
        "pointer": operation.pointer,
    }
    for key, value in (("operation_id", operation.operation_id), ("summary", operation.summary),
                       ("description", operation.description)):
        if value:
            details[key] = value
    if operation.tags:
        details["tags"] = operation.tags
    if operation.deprecated:
        details["deprecated"] = True
    details["servers"] = [server.url for server in (operation.servers or spec.servers)]
    details["parameters"] = [_parameter_dict(parameter, summarizer) for parameter in operation.parameters]
    if operation.request_body is not None:
        details["request_body"] = _request_body_dict(operation.request_body, summarizer)
    details["responses"] = [_response_dict(response, summarizer) for response in operation.responses]
    details["security"] = analyze_operation_security(spec, operation).to_dict()
    details["missing_information"] = missing_information(operation)
    issues = operation_issues(spec, operation)
    if issues:
        details["issues"] = issues
    details["examples_note"] = "Exemplos listados são os documentados na especificação."
    return details


def missing_information(operation: Operation) -> list[str]:
    """Lacunas do contrato que limitam explicação, testes ou geração de collection."""
    gaps = []
    if not operation.summary and not operation.description:
        gaps.append("Operação sem summary ou description.")
    if not operation.responses:
        gaps.append("Nenhuma resposta documentada.")
    elif not any(response.status_code.startswith("2") for response in operation.responses):
        gaps.append("Nenhuma resposta de sucesso (2xx) documentada.")
    elif not any(response.status_code[:1] in ("4", "5") for response in operation.responses):
        gaps.append("Nenhuma resposta de erro (4xx/5xx) documentada.")
    for parameter in operation.parameters:
        if parameter.schema is None:
            gaps.append(f"Parâmetro '{parameter.name}' ({parameter.location}) sem schema.")
    body = operation.request_body
    if body is not None:
        if not body.content:
            gaps.append("Request body sem content type declarado.")
        elif all(media.schema is None for media in body.content):
            gaps.append("Request body sem schema.")
        elif not any(media.has_example or media.examples for media in body.content):
            gaps.append("Request body sem exemplo documentado.")
    return gaps


def operation_issues(spec: ApiSpec, operation: Operation) -> list[dict[str, str]]:
    prefix = operation.pointer
    return [issue.to_dict() for issue in spec.issues
            if issue.severity is not Severity.INFO and issue.pointer.startswith(prefix)]


# ------------------------------------------------------------------ helpers


def _searchable_text(operation: Operation) -> str:
    parts = [operation.path, operation.operation_id or "", operation.summary or "", operation.description or ""]
    return " ".join(parts + operation.tags).lower()


def _endpoint_row(operation: Operation, status: AuthStatus) -> dict[str, Any]:
    row: dict[str, Any] = {"method": operation.method.upper(), "path": operation.path, "auth": status.value}
    if operation.operation_id:
        row["operation_id"] = operation.operation_id
    if operation.summary:
        row["summary"] = operation.summary
    if operation.tags:
        row["tags"] = operation.tags
    if operation.deprecated:
        row["deprecated"] = True
    return row


def _parameter_dict(parameter: Parameter, summarizer: SchemaSummarizer) -> dict[str, Any]:
    data: dict[str, Any] = {"name": parameter.name, "in": parameter.location, "required": parameter.required}
    if parameter.description:
        data["description"] = parameter.description
    if parameter.schema is not None:
        data["schema"] = summarizer.summarize(parameter.schema)
    if parameter.deprecated:
        data["deprecated"] = True
    _add_examples(data, parameter.example, parameter.has_example, parameter.examples)
    return data


def _request_body_dict(body: RequestBody, summarizer: SchemaSummarizer) -> dict[str, Any]:
    data: dict[str, Any] = {"required": body.required, "pointer": body.pointer,
                            "content": [_media_dict(media, summarizer) for media in body.content]}
    if body.description:
        data["description"] = body.description
    return data


def _response_dict(response: Response, summarizer: SchemaSummarizer) -> dict[str, Any]:
    data: dict[str, Any] = {"status": response.status_code}
    if response.description:
        data["description"] = response.description
    if response.content:
        data["content"] = [_media_dict(media, summarizer) for media in response.content]
    if response.headers:
        data["headers"] = sorted(response.headers)
    return data


def _media_dict(media: MediaType, summarizer: SchemaSummarizer) -> dict[str, Any]:
    data: dict[str, Any] = {"content_type": media.content_type}
    if media.schema is not None:
        data["schema"] = summarizer.summarize(media.schema)
    _add_examples(data, media.example, media.has_example, media.examples)
    return data


def _add_examples(data: dict[str, Any], example: Any, has_example: bool, examples: dict[str, Any]) -> None:
    documented: dict[str, Any] = {}
    if has_example:
        documented["example"] = example
    for name, item in list(examples.items())[:MAX_EXAMPLES_PER_MEDIA]:
        if isinstance(item, dict) and "value" in item:
            documented[name] = item["value"]
        elif isinstance(item, dict) and "$ref" in item:
            documented[name] = {"$ref": item["$ref"]}
    if not documented:
        return
    value, omitted = compact_value(documented, limit=MAX_DOCUMENTED_EXAMPLES_CHARS)
    data["documented_examples"] = value if not omitted else "omitido por tamanho; consulte o ponteiro de origem"
    if len(examples) > MAX_EXAMPLES_PER_MEDIA:
        data["documented_examples_omitted"] = len(examples) - MAX_EXAMPLES_PER_MEDIA
