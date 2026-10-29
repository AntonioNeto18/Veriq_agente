"""Normalização de Swagger 2.0, OpenAPI 3.0 e 3.1 para o modelo interno (`ApiSpec`).

O parser é tolerante: problemas estruturais viram `Issue`s rastreáveis por
JSON Pointer em vez de interromper a análise, para que o agente possa relatar
o que está ausente ou inválido na especificação.
"""

from __future__ import annotations

import re
from typing import Any

from .models import (
    HTTP_METHODS,
    PARAMETER_LOCATIONS,
    ApiSpec,
    Issue,
    MediaType,
    Operation,
    Parameter,
    RequestBody,
    Response,
    SecurityRequirements,
    SecurityScheme,
    Server,
    Severity,
    SpecVersion,
)
from .openapi_loader import LoadedDocument
from .ref_resolver import RefResolutionError, RefResolver, join_pointer

_PATH_TEMPLATE = re.compile(r"{([^{}]+)}")
_SWAGGER2_SCHEMA_KEYS = (
    "type", "format", "items", "enum", "default", "minimum", "maximum", "exclusiveMinimum",
    "exclusiveMaximum", "minLength", "maxLength", "pattern", "minItems", "maxItems",
    "uniqueItems", "multipleOf",
)
_SWAGGER2_OAUTH_FLOWS = {
    "implicit": "implicit",
    "password": "password",
    "application": "clientCredentials",
    "accessCode": "authorizationCode",
}
_FORM_CONTENT_TYPES = ("application/x-www-form-urlencoded", "multipart/form-data")


def parse_spec(loaded: LoadedDocument) -> ApiSpec:
    """Converte um documento carregado em `ApiSpec`."""
    return _SpecParser(loaded).parse()


class _SpecParser:
    def __init__(self, loaded: LoadedDocument) -> None:
        self.loaded = loaded
        self.doc = loaded.document
        self.version = loaded.version
        self.is_v2 = loaded.version is SpecVersion.SWAGGER_2_0
        self.resolver = RefResolver(self.doc)
        self.issues: list[Issue] = []

    # ------------------------------------------------------------------ geral

    def parse(self) -> ApiSpec:
        info = self.doc.get("info")
        if not isinstance(info, dict):
            self._issue("missing_info", "Objeto 'info' ausente ou inválido.", Severity.ERROR, "/info")
            info = {}
        for required in ("title", "version"):
            if required not in info:
                self._issue("missing_info_field", f"Campo 'info.{required}' ausente.", Severity.WARNING, "/info")

        spec = ApiSpec(
            version=self.version,
            version_string=self.loaded.version_string,
            source_name=self.loaded.source_name,
            document=self.doc,
            title=_as_str(info.get("title")),
            api_version=_as_str(info.get("version")),
            description=_as_str(info.get("description")),
        )
        spec.servers = self._parse_v2_servers() if self.is_v2 else self._parse_root_servers()
        spec.security_schemes = self._parse_security_schemes()
        if "security" in self.doc:
            spec.global_security = self._parse_security(self.doc["security"], "/security")
        spec.schema_names = self._parse_schema_names()
        spec.tags = [tag for tag in self.doc.get("tags", []) if isinstance(tag, dict)] if isinstance(
            self.doc.get("tags"), list
        ) else []
        spec.operations = self._parse_paths()
        self._check_duplicate_operation_ids(spec.operations)
        spec.references = self.resolver.collect_references()
        self._report_references(spec)
        spec.issues = self.issues
        return spec

    def _issue(self, code: str, message: str, severity: Severity, pointer: str) -> None:
        self.issues.append(Issue(code, message, severity, pointer))

    def _deref(self, node: Any, pointer: str) -> tuple[Any, str] | None:
        """Resolve `$ref` registrando um Issue em caso de falha."""
        try:
            resolved = self.resolver.deref(node, pointer)
        except RefResolutionError as error:
            severity = Severity.WARNING if "externa" in error.reason else Severity.ERROR
            self._issue("unresolved_ref", str(error), severity, pointer)
            return None
        return resolved.value, resolved.pointer

    # --------------------------------------------------------------- servers

    def _parse_root_servers(self) -> list[Server]:
        if "servers" not in self.doc:
            self._issue(
                "default_server",
                "Nenhum 'servers' declarado; pela especificação o padrão é '/' (URL relativa).",
                Severity.INFO,
                "/servers",
            )
            return [Server(url="/")]
        return self._parse_servers(self.doc["servers"], "/servers")

    def _parse_servers(self, value: Any, pointer: str) -> list[Server]:
        if not isinstance(value, list):
            self._issue("invalid_servers", "'servers' deve ser uma lista.", Severity.WARNING, pointer)
            return []
        servers = []
        for index, item in enumerate(value):
            if isinstance(item, dict) and isinstance(item.get("url"), str):
                variables = item.get("variables") if isinstance(item.get("variables"), dict) else {}
                servers.append(Server(item["url"], _as_str(item.get("description")), variables))
            else:
                self._issue("invalid_server", "Servidor sem 'url' válida.", Severity.WARNING,
                            join_pointer(pointer, index))
        return servers

    def _parse_v2_servers(self) -> list[Server]:
        host = _as_str(self.doc.get("host"))
        base_path = _as_str(self.doc.get("basePath")) or ""
        if not host:
            self._issue(
                "missing_host",
                "'host' não declarado; a URL-base é relativa ao local onde a especificação é servida.",
                Severity.INFO,
                "/host",
            )
            return [Server(url=base_path or "/")]
        schemes = [s for s in self.doc.get("schemes", []) if isinstance(s, str)] if isinstance(
            self.doc.get("schemes"), list
        ) else []
        if not schemes:
            self._issue("missing_schemes", "'schemes' não declarado; protocolo da URL-base indefinido.",
                        Severity.WARNING, "/schemes")
            return [Server(url=f"{host}{base_path}")]
        return [Server(url=f"{scheme}://{host}{base_path}") for scheme in schemes]

    # -------------------------------------------------------------- security

    def _parse_security_schemes(self) -> dict[str, SecurityScheme]:
        if self.is_v2:
            container, pointer = self.doc.get("securityDefinitions"), "/securityDefinitions"
        else:
            components = self.doc.get("components") if isinstance(self.doc.get("components"), dict) else {}
            container, pointer = components.get("securitySchemes"), "/components/securitySchemes"
        if not isinstance(container, dict):
            return {}
        schemes: dict[str, SecurityScheme] = {}
        for name, raw in container.items():
            item_pointer = join_pointer(pointer, name)
            resolved = self._deref(raw, item_pointer)
            if resolved is None:
                continue
            value, value_pointer = resolved
            if not isinstance(value, dict) or not isinstance(value.get("type"), str):
                self._issue("invalid_security_scheme", f"Esquema de segurança '{name}' sem 'type' válido.",
                            Severity.WARNING, item_pointer)
                continue
            schemes[name] = self._build_v2_scheme(name, value, value_pointer) if self.is_v2 else \
                self._build_v3_scheme(name, value, value_pointer)
        return schemes

    def _build_v3_scheme(self, name: str, value: dict[str, Any], pointer: str) -> SecurityScheme:
        scheme = SecurityScheme(name=name, type=value["type"], pointer=pointer, description=_as_str(value.get("description")))
        scheme.scheme = _as_str(value.get("scheme"), lower=True)
        scheme.bearer_format = _as_str(value.get("bearerFormat"))
        scheme.location = _as_str(value.get("in"))
        scheme.parameter_name = _as_str(value.get("name"))
        scheme.flows = value.get("flows") if isinstance(value.get("flows"), dict) else {}
        scheme.openid_connect_url = _as_str(value.get("openIdConnectUrl"))
        return scheme

    def _build_v2_scheme(self, name: str, value: dict[str, Any], pointer: str) -> SecurityScheme:
        kind = value["type"]
        scheme = SecurityScheme(name=name, type=kind, pointer=pointer, description=_as_str(value.get("description")))
        if kind == "basic":
            scheme.type, scheme.scheme = "http", "basic"
        elif kind == "apiKey":
            scheme.location = _as_str(value.get("in"))
            scheme.parameter_name = _as_str(value.get("name"))
        elif kind == "oauth2":
            flow = _SWAGGER2_OAUTH_FLOWS.get(str(value.get("flow")))
            if flow is None:
                self._issue("invalid_oauth_flow", f"Fluxo OAuth2 desconhecido em '{name}'.", Severity.WARNING, pointer)
            else:
                details = {key: value[key] for key in ("authorizationUrl", "tokenUrl") if key in value}
                details["scopes"] = value.get("scopes") if isinstance(value.get("scopes"), dict) else {}
                scheme.flows = {flow: details}
        return scheme

    def _parse_security(self, value: Any, pointer: str) -> SecurityRequirements | None:
        if not isinstance(value, list):
            self._issue("invalid_security", "'security' deve ser uma lista de requisitos.", Severity.ERROR, pointer)
            return None
        requirements: SecurityRequirements = []
        for index, item in enumerate(value):
            item_pointer = join_pointer(pointer, index)
            if not isinstance(item, dict):
                self._issue("invalid_security", "Requisito de segurança deve ser um objeto.", Severity.ERROR, item_pointer)
                continue
            requirement: dict[str, list[str]] = {}
            for name, scopes in item.items():
                if not isinstance(scopes, list):
                    self._issue("invalid_security", f"Scopes de '{name}' devem ser uma lista.", Severity.ERROR,
                                join_pointer(item_pointer, name))
                    scopes = []
                requirement[name] = [str(scope) for scope in scopes]
            requirements.append(requirement)
        return requirements

    # --------------------------------------------------------------- schemas

    def _parse_schema_names(self) -> dict[str, str]:
        if self.is_v2:
            container, pointer = self.doc.get("definitions"), "/definitions"
        else:
            components = self.doc.get("components") if isinstance(self.doc.get("components"), dict) else {}
            container, pointer = components.get("schemas"), "/components/schemas"
        if not isinstance(container, dict):
            return {}
        return {name: join_pointer(pointer, name) for name in container}

    # ----------------------------------------------------------------- paths

    def _parse_paths(self) -> list[Operation]:
        paths = self.doc.get("paths")
        if paths is None:
            if self.version is SpecVersion.OPENAPI_3_1:
                self._issue("no_paths", "A especificação não declara 'paths'.", Severity.INFO, "/paths")
            else:
                self._issue("missing_paths", "Campo obrigatório 'paths' ausente.", Severity.ERROR, "/paths")
            return []
        if not isinstance(paths, dict):
            self._issue("invalid_paths", "'paths' deve ser um objeto.", Severity.ERROR, "/paths")
            return []
        if self.version is SpecVersion.OPENAPI_3_1 and isinstance(self.doc.get("webhooks"), dict):
            self._issue("webhooks_ignored", "Webhooks declarados não são analisados como endpoints.",
                        Severity.INFO, "/webhooks")

        operations: list[Operation] = []
        for path, raw_item in paths.items():
            if path.startswith("x-"):
                continue
            item_pointer = join_pointer("/paths", path)
            if not path.startswith("/"):
                self._issue("invalid_path", f"Path '{path}' deve começar com '/'.", Severity.WARNING, item_pointer)
            resolved = self._deref(raw_item, item_pointer)
            if resolved is None:
                continue
            path_item, path_item_pointer = resolved
            if not isinstance(path_item, dict):
                self._issue("invalid_path_item", f"Path '{path}' não é um objeto.", Severity.ERROR, item_pointer)
                continue
            operations.extend(self._parse_path_item(path, path_item, path_item_pointer))
        return operations

    def _parse_path_item(self, path: str, item: dict[str, Any], pointer: str) -> list[Operation]:
        shared_params = item.get("parameters", [])
        path_servers = self._parse_servers(item["servers"], join_pointer(pointer, "servers")) \
            if not self.is_v2 and "servers" in item else []
        operations = []
        for method in HTTP_METHODS:
            if method not in item:
                continue
            op_pointer = join_pointer(pointer, method)
            raw = item[method]
            if not isinstance(raw, dict):
                self._issue("invalid_operation", f"Operação {method.upper()} {path} não é um objeto.",
                            Severity.ERROR, op_pointer)
                continue
            operations.append(self._parse_operation(path, method, raw, op_pointer, shared_params, pointer, path_servers))
        return operations

    def _parse_operation(
        self,
        path: str,
        method: str,
        raw: dict[str, Any],
        pointer: str,
        shared_params: Any,
        path_item_pointer: str,
        path_servers: list[Server],
    ) -> Operation:
        operation = Operation(
            method=method,
            path=path,
            pointer=pointer,
            operation_id=_as_str(raw.get("operationId")),
            summary=_as_str(raw.get("summary")),
            description=_as_str(raw.get("description")),
            tags=[str(tag) for tag in raw.get("tags", [])] if isinstance(raw.get("tags"), list) else [],
            deprecated=raw.get("deprecated") is True,
        )
        raw_params = self._merge_parameters(
            shared_params, join_pointer(path_item_pointer, "parameters"),
            raw.get("parameters", []), join_pointer(pointer, "parameters"),
        )
        if self.is_v2:
            operation.parameters, operation.request_body = self._parse_v2_parameters(raw, raw_params, pointer)
        else:
            operation.parameters = [p for p in (self._parse_v3_parameter(v, ptr) for v, ptr in raw_params) if p]
            if "requestBody" in raw:
                operation.request_body = self._parse_v3_request_body(raw["requestBody"], join_pointer(pointer, "requestBody"))
        self._check_path_parameters(operation)
        operation.responses = self._parse_responses(raw, pointer)
        if "security" in raw:
            operation.security = self._parse_security(raw["security"], join_pointer(pointer, "security"))
        if not self.is_v2:
            operation.servers = self._parse_servers(raw["servers"], join_pointer(pointer, "servers")) \
                if "servers" in raw else path_servers
        return operation

    # ------------------------------------------------------------ parameters

    def _merge_parameters(
        self, shared: Any, shared_pointer: str, own: Any, own_pointer: str
    ) -> list[tuple[dict[str, Any], str]]:
        """Combina parâmetros do path e da operação; os da operação prevalecem por (name, in)."""
        merged: dict[tuple[str, str], tuple[dict[str, Any], str]] = {}
        for values, base_pointer in ((shared, shared_pointer), (own, own_pointer)):
            if not isinstance(values, list):
                self._issue("invalid_parameters", "'parameters' deve ser uma lista.", Severity.WARNING, base_pointer)
                continue
            for index, raw in enumerate(values):
                entry_pointer = join_pointer(base_pointer, index)
                resolved = self._deref(raw, entry_pointer)
                if resolved is None:
                    continue
                value, value_pointer = resolved
                if not isinstance(value, dict) or not isinstance(value.get("name"), str) or not isinstance(
                    value.get("in"), str
                ):
                    self._issue("invalid_parameter", "Parâmetro sem 'name' ou 'in' válidos.", Severity.WARNING,
                                entry_pointer)
                    continue
                name = value["name"].lower() if value["in"] == "header" else value["name"]
                merged[(name, value["in"])] = (value, value_pointer)
        return list(merged.values())

    def _parse_v3_parameter(self, value: dict[str, Any], pointer: str) -> Parameter | None:
        location = value["in"]
        if location not in PARAMETER_LOCATIONS:
            self._issue("invalid_parameter_location", f"Localização de parâmetro inválida: '{location}'.",
                        Severity.WARNING, pointer)
            return None
        schema = value.get("schema") if isinstance(value.get("schema"), dict) else None
        if schema is None and isinstance(value.get("content"), dict):
            media = self._parse_content(value["content"], join_pointer(pointer, "content"))
            schema = media[0].schema if media else None
        parameter = Parameter(
            name=value["name"],
            location=location,
            required=self._required_flag(value, location, pointer),
            pointer=pointer,
            description=_as_str(value.get("description")),
            schema=schema,
            deprecated=value.get("deprecated") is True,
        )
        _copy_examples(value, parameter)
        return parameter

    def _parse_v2_parameters(
        self, raw: dict[str, Any], params: list[tuple[dict[str, Any], str]], pointer: str
    ) -> tuple[list[Parameter], RequestBody | None]:
        parameters: list[Parameter] = []
        body: tuple[dict[str, Any], str] | None = None
        form_fields: list[tuple[dict[str, Any], str]] = []
        for value, value_pointer in params:
            location = value["in"]
            if location == "body":
                body = (value, value_pointer)
            elif location == "formData":
                form_fields.append((value, value_pointer))
            elif location in PARAMETER_LOCATIONS:
                parameter = Parameter(
                    name=value["name"],
                    location=location,
                    required=self._required_flag(value, location, value_pointer),
                    pointer=value_pointer,
                    description=_as_str(value.get("description")),
                    schema=_v2_inline_schema(value),
                )
                parameters.append(parameter)
            else:
                self._issue("invalid_parameter_location", f"Localização de parâmetro inválida: '{location}'.",
                            Severity.WARNING, value_pointer)
        consumes = self._v2_media_types(raw, "consumes")
        if body is not None:
            return parameters, self._v2_body(body, consumes, pointer)
        if form_fields:
            return parameters, self._v2_form_body(form_fields, consumes, pointer)
        return parameters, None

    def _v2_body(self, body: tuple[dict[str, Any], str], consumes: list[str], op_pointer: str) -> RequestBody:
        value, value_pointer = body
        if not consumes:
            self._issue("assumed_content_type",
                        "'consumes' não declarado; tipo de conteúdo do body assumido como application/json.",
                        Severity.INFO, join_pointer(op_pointer, "consumes"))
            consumes = ["application/json"]
        schema = value.get("schema") if isinstance(value.get("schema"), dict) else None
        return RequestBody(
            required=value.get("required") is True,
            pointer=value_pointer,
            description=_as_str(value.get("description")),
            content=[MediaType(content_type=media, schema=schema) for media in consumes],
        )

    def _v2_form_body(
        self, fields: list[tuple[dict[str, Any], str]], consumes: list[str], op_pointer: str
    ) -> RequestBody:
        properties = {value["name"]: _v2_inline_schema(value) or {} for value, _ in fields}
        required = [value["name"] for value, _ in fields if value.get("required") is True]
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        media_types = [media for media in consumes if media in _FORM_CONTENT_TYPES]
        if not media_types:
            has_file = any(value.get("type") == "file" for value, _ in fields)
            media_types = ["multipart/form-data" if has_file else "application/x-www-form-urlencoded"]
            self._issue("assumed_content_type",
                        f"Tipo de conteúdo do formulário assumido como {media_types[0]}.",
                        Severity.INFO, join_pointer(op_pointer, "consumes"))
        return RequestBody(
            required=bool(required),
            pointer=fields[0][1],
            content=[MediaType(content_type=media, schema=schema) for media in media_types],
        )

    def _v2_media_types(self, raw: dict[str, Any], key: str) -> list[str]:
        value = raw.get(key, self.doc.get(key))
        return [str(item) for item in value] if isinstance(value, list) else []

    def _required_flag(self, value: dict[str, Any], location: str, pointer: str) -> bool:
        if location == "path" and value.get("required") is not True:
            self._issue("path_parameter_not_required",
                        f"Parâmetro de path '{value['name']}' deveria declarar required: true.",
                        Severity.WARNING, pointer)
            return True
        return value.get("required") is True

    def _check_path_parameters(self, operation: Operation) -> None:
        declared = {p.name for p in operation.parameters if p.location == "path"}
        for name in _PATH_TEMPLATE.findall(operation.path):
            if name not in declared:
                self._issue("undeclared_path_parameter",
                            f"Variável '{{{name}}}' do path não possui parâmetro declarado em {operation.key}.",
                            Severity.WARNING, operation.pointer)

    # ------------------------------------------------- request/response body

    def _parse_v3_request_body(self, raw: Any, pointer: str) -> RequestBody | None:
        resolved = self._deref(raw, pointer)
        if resolved is None:
            return None
        value, value_pointer = resolved
        if not isinstance(value, dict):
            self._issue("invalid_request_body", "'requestBody' deve ser um objeto.", Severity.ERROR, pointer)
            return None
        content = self._parse_content(value.get("content"), join_pointer(value_pointer, "content"))
        if not content:
            self._issue("missing_request_content", "'requestBody' sem 'content' declarado.", Severity.WARNING,
                        value_pointer)
        return RequestBody(
            required=value.get("required") is True,
            pointer=value_pointer,
            description=_as_str(value.get("description")),
            content=content,
        )

    def _parse_content(self, value: Any, pointer: str) -> list[MediaType]:
        if not isinstance(value, dict):
            return []
        media_types = []
        for content_type, raw in value.items():
            if not isinstance(raw, dict):
                continue
            media = MediaType(
                content_type=content_type,
                schema=raw.get("schema") if isinstance(raw.get("schema"), dict) else None,
            )
            _copy_examples(raw, media)
            media_types.append(media)
        return media_types

    def _parse_responses(self, raw: dict[str, Any], op_pointer: str) -> list[Response]:
        pointer = join_pointer(op_pointer, "responses")
        value = raw.get("responses")
        if not isinstance(value, dict) or not value:
            self._issue("missing_responses", "Operação sem respostas documentadas.", Severity.WARNING, pointer)
            return []
        produces = self._v2_media_types(raw, "produces") if self.is_v2 else []
        responses = []
        for status, raw_response in value.items():
            if status.startswith("x-"):
                continue
            item_pointer = join_pointer(pointer, status)
            resolved = self._deref(raw_response, item_pointer)
            if resolved is None:
                continue
            response, response_pointer = resolved
            if not isinstance(response, dict):
                self._issue("invalid_response", f"Resposta '{status}' não é um objeto.", Severity.ERROR, item_pointer)
                continue
            responses.append(self._build_response(status, response, response_pointer, produces))
        return responses

    def _build_response(self, status: str, value: dict[str, Any], pointer: str, produces: list[str]) -> Response:
        if "description" not in value:
            self._issue("missing_response_description", f"Resposta '{status}' sem 'description'.",
                        Severity.INFO, pointer)
        headers = value.get("headers") if isinstance(value.get("headers"), dict) else {}
        response = Response(status_code=status, pointer=pointer, description=_as_str(value.get("description")),
                            headers={name: h for name, h in headers.items() if isinstance(h, dict)})
        if not self.is_v2:
            response.content = self._parse_content(value.get("content"), join_pointer(pointer, "content"))
            return response
        schema = value.get("schema") if isinstance(value.get("schema"), dict) else None
        examples = value.get("examples") if isinstance(value.get("examples"), dict) else {}
        media_names = produces or list(examples) or (["application/json"] if schema else [])
        for media_name in media_names:
            media = MediaType(content_type=media_name, schema=schema)
            if media_name in examples:
                media.example, media.has_example = examples[media_name], True
            response.content.append(media)
        return response

    # ---------------------------------------------------------------- checks

    def _check_duplicate_operation_ids(self, operations: list[Operation]) -> None:
        seen: dict[str, Operation] = {}
        for operation in operations:
            if operation.operation_id is None:
                continue
            if operation.operation_id in seen:
                self._issue("duplicate_operation_id",
                            f"operationId '{operation.operation_id}' repetido em {seen[operation.operation_id].key} "
                            f"e {operation.key}.", Severity.WARNING, operation.pointer)
            else:
                seen[operation.operation_id] = operation

    def _report_references(self, spec: ApiSpec) -> None:
        reported = {issue.pointer for issue in self.issues if issue.code == "unresolved_ref"}
        for reference in spec.references:
            parent = reference.pointer.rsplit("/", 1)[0]
            if reference.resolved or parent in reported:
                continue
            if reference.external:
                self._issue("external_ref", f"Referência externa '{reference.ref}' não foi acessada.",
                            Severity.WARNING, reference.pointer)
            else:
                self._issue("broken_ref", f"Referência interna '{reference.ref}' não existe no documento.",
                            Severity.ERROR, reference.pointer)


def _as_str(value: Any, *, lower: bool = False) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value)
    return text.lower() if lower else text


def _copy_examples(source: dict[str, Any], target: Parameter | MediaType) -> None:
    if "example" in source:
        target.example, target.has_example = source["example"], True
    if isinstance(source.get("examples"), dict):
        target.examples = source["examples"]


def _v2_inline_schema(value: dict[str, Any]) -> dict[str, Any] | None:
    """Swagger 2.0 declara tipo/limites diretamente no parâmetro; converte para um schema."""
    schema = {key: value[key] for key in _SWAGGER2_SCHEMA_KEYS if key in value}
    return schema or None
