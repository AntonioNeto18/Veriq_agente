"""Análise dos requisitos de segurança *declarados* na especificação.

O resultado descreve o contrato, não o comportamento real do servidor: um
endpoint sem segurança declarada não é necessariamente público em produção.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .models import ApiSpec, Issue, Operation, SecurityScheme, Severity

KNOWN_SCHEME_TYPES = {"apiKey", "http", "oauth2", "openIdConnect", "mutualTLS"}
_OAUTH_FLOW_URLS = {
    "implicit": ("authorizationUrl",),
    "password": ("tokenUrl",),
    "clientCredentials": ("tokenUrl",),
    "authorizationCode": ("authorizationUrl", "tokenUrl"),
}
DISCLAIMER = (
    "Resultado baseado apenas no que está declarado na especificação; "
    "o comportamento real do servidor não foi verificado."
)


class AuthStatus(str, Enum):
    DECLARED_REQUIRED = "declared_required"
    NONE_DECLARED = "none_declared"
    INDETERMINATE = "indeterminate"


class SecuritySource(str, Enum):
    OPERATION = "operation"  # a operação declara `security` próprio
    GLOBAL = "global"  # herdado do `security` raiz
    OPERATION_EMPTY_OVERRIDE = "operation_empty_override"  # `security: []` na operação
    NOT_DECLARED = "not_declared"  # nem operação nem raiz declaram


@dataclass
class SchemeUsage:
    name: str
    scopes: list[str]
    defined: bool
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"scheme": self.name, "scopes": self.scopes}
        data["type"] = self.description if self.defined else "não definido em securitySchemes"
        return data


@dataclass
class OperationSecurity:
    operation_key: str
    operation_id: str | None
    status: AuthStatus
    source: SecuritySource
    pointer: str
    # Lista de alternativas (OR); cada alternativa combina esquemas com AND.
    alternatives: list[list[SchemeUsage]] = field(default_factory=list)
    optional: bool = False  # existe alternativa vazia `{}`: autenticação opcional
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "operation": self.operation_key,
            "status": self.status.value,
            "source": self.source.value,
            "pointer": self.pointer,
        }
        if self.operation_id:
            data["operation_id"] = self.operation_id
        if self.alternatives:
            data["alternatives"] = [[usage.to_dict() for usage in alternative] for alternative in self.alternatives]
        if self.optional:
            data["optional"] = True
        if self.notes:
            data["notes"] = self.notes
        return data


def describe_scheme(scheme: SecurityScheme) -> str:
    """Descrição curta e legível de um esquema de segurança."""
    if scheme.type == "http":
        if scheme.scheme == "bearer":
            return f"HTTP Bearer ({scheme.bearer_format})" if scheme.bearer_format else "HTTP Bearer"
        if scheme.scheme == "basic":
            return "HTTP Basic"
        return f"HTTP {scheme.scheme}" if scheme.scheme else "HTTP (scheme não declarado)"
    if scheme.type == "apiKey":
        return f"API key em {scheme.location or '?'}: {scheme.parameter_name or '?'}"
    if scheme.type == "oauth2":
        flows = ", ".join(sorted(scheme.flows)) or "nenhum fluxo declarado"
        return f"OAuth 2.0 ({flows})"
    if scheme.type == "openIdConnect":
        return "OpenID Connect"
    if scheme.type == "mutualTLS":
        return "Mutual TLS"
    return f"Tipo desconhecido: {scheme.type}"


def scheme_to_dict(scheme: SecurityScheme) -> dict[str, Any]:
    data: dict[str, Any] = {"name": scheme.name, "type": scheme.type, "summary": describe_scheme(scheme),
                            "pointer": scheme.pointer}
    for key, value in (("scheme", scheme.scheme), ("bearer_format", scheme.bearer_format),
                       ("in", scheme.location), ("parameter_name", scheme.parameter_name),
                       ("openid_connect_url", scheme.openid_connect_url)):
        if value:
            data[key] = value
    if scheme.flows:
        data["flows"] = {
            name: {key: value for key, value in flow.items() if key in ("authorizationUrl", "tokenUrl", "scopes")}
            for name, flow in scheme.flows.items() if isinstance(flow, dict)
        }
    return data


def analyze_operation_security(spec: ApiSpec, operation: Operation) -> OperationSecurity:
    """Determina a segurança efetiva declarada para uma operação."""
    if operation.security is not None or _operation_security_invalid(spec, operation):
        requirements = operation.security or []
        pointer = f"{operation.pointer}/security"
        source = SecuritySource.OPERATION_EMPTY_OVERRIDE if operation.security == [] else SecuritySource.OPERATION
    elif spec.global_security is not None:
        requirements, pointer, source = spec.global_security, "/security", SecuritySource.GLOBAL
    else:
        requirements, pointer, source = [], operation.pointer, SecuritySource.NOT_DECLARED

    result = OperationSecurity(operation.key, operation.operation_id, AuthStatus.NONE_DECLARED, source, pointer)
    if _has_invalid_security(spec, operation):
        result.status = AuthStatus.INDETERMINATE
        result.notes.append("O campo 'security' aplicável é inválido e não pôde ser interpretado com confiança.")
        return result
    if not requirements:
        if source is SecuritySource.OPERATION_EMPTY_OVERRIDE and spec.global_security:
            result.notes.append("A operação remove explicitamente a segurança global com 'security: []'.")
        return result

    for requirement in requirements:
        if not requirement:
            result.optional = True
            continue
        result.alternatives.append([_usage(spec, name, scopes, result) for name, scopes in requirement.items()])

    if result.notes:
        result.status = AuthStatus.INDETERMINATE
    elif result.optional:
        result.status = AuthStatus.NONE_DECLARED
        result.notes.append("Autenticação declarada como opcional: uma das alternativas é vazia ({}).")
    else:
        result.status = AuthStatus.DECLARED_REQUIRED
    return result


def analyze_all_operations(spec: ApiSpec) -> list[OperationSecurity]:
    return [analyze_operation_security(spec, operation) for operation in spec.operations]


def security_overview(spec: ApiSpec) -> dict[str, Any]:
    """Resumo global: esquemas, segurança raiz e contagem de operações por situação."""
    results = analyze_all_operations(spec)
    counts = {status.value: 0 for status in AuthStatus}
    for result in results:
        counts[result.status.value] += 1
    return {
        "disclaimer": DISCLAIMER,
        "security_schemes": [scheme_to_dict(scheme) for scheme in spec.security_schemes.values()],
        "global_security": spec.global_security,
        "operations_by_status": counts,
    }


def find_security_gaps(spec: ApiSpec) -> list[Issue]:
    """Lista informações de autenticação ausentes, inconsistentes ou não interpretáveis."""
    gaps: list[Issue] = [issue for issue in spec.issues if issue.code in (
        "invalid_security", "invalid_security_scheme", "invalid_oauth_flow")]
    gaps.extend(_scheme_definition_gaps(spec))
    used = _collect_used_schemes(spec)
    for name in sorted(used - set(spec.security_schemes)):
        gaps.append(Issue("undefined_security_scheme",
                          f"Esquema '{name}' é exigido em requisitos de segurança mas não está definido.",
                          Severity.ERROR, _schemes_pointer(spec)))
    for name in sorted(set(spec.security_schemes) - used):
        gaps.append(Issue("unused_security_scheme", f"Esquema '{name}' está definido mas não é exigido por "
                          "nenhuma operação.", Severity.INFO, spec.security_schemes[name].pointer))
    gaps.extend(_scope_gaps(spec))
    gaps.extend(_response_consistency_gaps(spec))
    if not spec.security_schemes and spec.global_security is None and all(
            op.security is None for op in spec.operations):
        gaps.append(Issue("no_security_declared", "A especificação não declara nenhum esquema nem requisito de "
                          "segurança.", Severity.INFO, "/"))
    return gaps


# ------------------------------------------------------------------ helpers


def _usage(spec: ApiSpec, name: str, scopes: list[str], result: OperationSecurity) -> SchemeUsage:
    scheme = spec.security_schemes.get(name)
    if scheme is None:
        result.notes.append(f"Esquema '{name}' não está definido em securitySchemes/securityDefinitions.")
        return SchemeUsage(name, scopes, defined=False)
    if scheme.type not in KNOWN_SCHEME_TYPES:
        result.notes.append(f"Esquema '{name}' tem tipo não reconhecido: '{scheme.type}'.")
    elif scheme.type == "apiKey" and (not scheme.location or not scheme.parameter_name):
        result.notes.append(f"API key '{name}' não declara 'in' e/ou 'name'.")
    return SchemeUsage(name, scopes, defined=True, description=describe_scheme(scheme))


def _invalid_security_pointers(spec: ApiSpec) -> list[str]:
    return [issue.pointer for issue in spec.issues if issue.code == "invalid_security"]


def _operation_security_invalid(spec: ApiSpec, operation: Operation) -> bool:
    """Inclui o caso em que `security` da operação nem é lista (vira `None` no modelo)."""
    pointer = f"{operation.pointer}/security"
    return any(item.startswith(pointer) for item in _invalid_security_pointers(spec))


def _has_invalid_security(spec: ApiSpec, operation: Operation) -> bool:
    if _operation_security_invalid(spec, operation):
        return True
    return operation.security is None and any(
        item.startswith("/security") for item in _invalid_security_pointers(spec))


def _collect_used_schemes(spec: ApiSpec) -> set[str]:
    used: set[str] = set()
    for requirements in [spec.global_security or []] + [op.security or [] for op in spec.operations]:
        for requirement in requirements:
            used.update(requirement)
    return used


def _schemes_pointer(spec: ApiSpec) -> str:
    return "/securityDefinitions" if spec.version.value == "2.0" else "/components/securitySchemes"


def _scheme_definition_gaps(spec: ApiSpec) -> list[Issue]:
    gaps = []
    for scheme in spec.security_schemes.values():
        problem = None
        if scheme.type not in KNOWN_SCHEME_TYPES:
            problem = f"tipo '{scheme.type}' não reconhecido"
        elif scheme.type == "apiKey" and (not scheme.location or not scheme.parameter_name):
            problem = "API key sem 'in' e/ou 'name'"
        elif scheme.type == "http" and not scheme.scheme:
            problem = "esquema HTTP sem 'scheme'"
        elif scheme.type == "openIdConnect" and not scheme.openid_connect_url:
            problem = "OpenID Connect sem 'openIdConnectUrl'"
        elif scheme.type == "oauth2":
            problem = _oauth_problem(scheme)
        if problem:
            gaps.append(Issue("incomplete_security_scheme", f"Esquema '{scheme.name}': {problem}.",
                              Severity.WARNING, scheme.pointer))
    return gaps


def _oauth_problem(scheme: SecurityScheme) -> str | None:
    if not scheme.flows:
        return "OAuth 2.0 sem fluxos declarados"
    for flow_name, flow in scheme.flows.items():
        if not isinstance(flow, dict):
            return f"fluxo '{flow_name}' inválido"
        missing = [url for url in _OAUTH_FLOW_URLS.get(flow_name, ()) if not flow.get(url)]
        if missing:
            return f"fluxo '{flow_name}' sem {', '.join(missing)}"
    return None


def _declared_scopes(scheme: SecurityScheme) -> set[str]:
    scopes: set[str] = set()
    for flow in scheme.flows.values():
        if isinstance(flow, dict) and isinstance(flow.get("scopes"), dict):
            scopes.update(flow["scopes"])
    return scopes


def _scope_gaps(spec: ApiSpec) -> list[Issue]:
    gaps = []
    sources = [("/security", spec.global_security or [])] + [
        (f"{op.pointer}/security", op.security or []) for op in spec.operations]
    for pointer, requirements in sources:
        for requirement in requirements:
            for name, scopes in requirement.items():
                scheme = spec.security_schemes.get(name)
                if scheme is None or scheme.type != "oauth2":
                    continue
                for scope in sorted(set(scopes) - _declared_scopes(scheme)):
                    gaps.append(Issue("undeclared_scope", f"Scope '{scope}' exigido de '{name}' não está "
                                      "declarado nos fluxos OAuth.", Severity.WARNING, pointer))
    return gaps


def _response_consistency_gaps(spec: ApiSpec) -> list[Issue]:
    gaps = []
    for operation in spec.operations:
        status = analyze_operation_security(spec, operation).status
        codes = {response.status_code for response in operation.responses}
        if status is AuthStatus.DECLARED_REQUIRED and not codes & {"401", "403"}:
            gaps.append(Issue("auth_errors_not_documented", f"{operation.key} declara autenticação mas não "
                              "documenta respostas 401/403.", Severity.INFO, operation.pointer))
        if status is AuthStatus.NONE_DECLARED and "401" in codes:
            gaps.append(Issue("auth_response_without_security", f"{operation.key} documenta 401 mas não declara "
                              "requisito de segurança.", Severity.WARNING, operation.pointer))
    return gaps
