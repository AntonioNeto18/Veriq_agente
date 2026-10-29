"""Modelo interno normalizado de uma especificação OpenAPI.

Swagger 2.0, OpenAPI 3.0 e OpenAPI 3.1 são convertidos para estas estruturas,
de modo que analisadores, planejador e gerador de collection trabalhem sobre
um único formato. Cada elemento guarda o JSON Pointer de origem (`pointer`)
para manter a rastreabilidade até o documento original.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

HTTP_METHODS: tuple[str, ...] = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
PARAMETER_LOCATIONS: tuple[str, ...] = ("path", "query", "header", "cookie")


class SpecVersion(str, Enum):
    SWAGGER_2_0 = "2.0"
    OPENAPI_3_0 = "3.0"
    OPENAPI_3_1 = "3.1"


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Issue:
    """Problema ou limitação encontrada durante a análise."""

    code: str
    message: str
    severity: Severity
    pointer: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "severity": self.severity.value, "pointer": self.pointer}


@dataclass(frozen=True)
class Reference:
    """Uma ocorrência de `$ref` no documento."""

    ref: str
    pointer: str
    external: bool
    resolved: bool


@dataclass
class Server:
    url: str
    description: str | None = None
    variables: dict[str, Any] = field(default_factory=dict)


@dataclass
class MediaType:
    content_type: str
    schema: dict[str, Any] | None = None
    example: Any = None
    has_example: bool = False
    examples: dict[str, Any] = field(default_factory=dict)


@dataclass
class Parameter:
    name: str
    location: str
    required: bool
    pointer: str
    description: str | None = None
    schema: dict[str, Any] | None = None
    deprecated: bool = False
    example: Any = None
    has_example: bool = False
    examples: dict[str, Any] = field(default_factory=dict)


@dataclass
class RequestBody:
    required: bool
    pointer: str
    description: str | None = None
    content: list[MediaType] = field(default_factory=list)


@dataclass
class Response:
    status_code: str
    pointer: str
    description: str | None = None
    content: list[MediaType] = field(default_factory=list)
    headers: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class SecurityScheme:
    """Esquema de segurança declarado (normalizado para a nomenclatura 3.x)."""

    name: str
    type: str
    pointer: str
    description: str | None = None
    scheme: str | None = None  # http: "bearer", "basic", ...
    bearer_format: str | None = None
    location: str | None = None  # apiKey: "header" | "query" | "cookie"
    parameter_name: str | None = None  # apiKey: nome do header/query/cookie
    flows: dict[str, Any] = field(default_factory=dict)  # oauth2
    openid_connect_url: str | None = None


# Cada alternativa é um dict {nome_do_scheme: [scopes]}; a lista é um OR entre
# alternativas e os itens de um mesmo dict são combinados com AND.
SecurityRequirements = list[dict[str, list[str]]]


@dataclass
class Operation:
    method: str
    path: str
    pointer: str
    operation_id: str | None = None
    summary: str | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    deprecated: bool = False
    parameters: list[Parameter] = field(default_factory=list)
    request_body: RequestBody | None = None
    responses: list[Response] = field(default_factory=list)
    # None = a operação não declara `security` (herda a global); [] = override explícito sem segurança.
    security: SecurityRequirements | None = None
    servers: list[Server] = field(default_factory=list)

    @property
    def key(self) -> str:
        """Identificador estável da operação, ex.: `GET /users/{id}`."""
        return f"{self.method.upper()} {self.path}"


@dataclass
class ApiSpec:
    version: SpecVersion
    version_string: str
    source_name: str
    document: dict[str, Any]
    title: str | None = None
    api_version: str | None = None
    description: str | None = None
    servers: list[Server] = field(default_factory=list)
    operations: list[Operation] = field(default_factory=list)
    security_schemes: dict[str, SecurityScheme] = field(default_factory=dict)
    global_security: SecurityRequirements | None = None
    schema_names: dict[str, str] = field(default_factory=dict)  # nome -> pointer
    tags: list[dict[str, Any]] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    def find_operation(self, identifier: str) -> Operation | None:
        """Localiza uma operação pelo operationId ou pela chave `METHOD /path`."""
        wanted = identifier.strip()
        for operation in self.operations:
            if operation.operation_id == wanted:
                return operation
        method, _, path = wanted.partition(" ")
        for operation in self.operations:
            if operation.method == method.lower() and operation.path == path.strip():
                return operation
        return None
