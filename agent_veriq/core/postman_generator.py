"""Geração de collections Postman v2.1.0 a partir do modelo normalizado.

A collection é um artefato para revisão e execução posterior pelo usuário: nada
aqui executa requisições. Credenciais são sempre variáveis vazias (`{{...}}`),
e asserções só são criadas para expectativas documentadas na especificação.
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import (
    BASE_URL_VARIABLE,
    COLLECTION_PREVIEW_REQUESTS,
    DEFAULT_MAX_SCENARIOS_PER_OPERATION,
    INVALID_CREDENTIAL,
    POSTMAN_SCHEMA_URL,
)
from .endpoint_analyzer import filter_operations, get_operation
from .models import ApiSpec, Operation, Parameter, Response, SecurityScheme
from .postman_validator import validate_collection
from .ref_resolver import RefResolver
from .schema_utils import SUGGESTED, ExampleBuilder, object_view
from .security_analyzer import AuthStatus, OperationSecurity, analyze_operation_security
from .test_planner import plan_operation_tests

_IGNORED_HEADER_PARAMETERS = {"accept", "content-type", "authorization"}
_OAUTH_GRANT_TYPES = {
    "authorizationCode": "authorization_code",
    "clientCredentials": "client_credentials",
    "password": "password_credentials",
    "implicit": "implicit",
}
_PATH_SEGMENT_VARIABLE = re.compile(r"^{([^{}]+)}$")
_PATH_TEMPLATE = re.compile(r"{([^{}]+)}")
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class CollectionGenerationError(Exception):
    """Escopo vazio ou collection inválida."""


@dataclass
class CollectionOptions:
    name: str | None = None
    include_tests: bool = True
    include_scenarios: bool = False
    max_scenarios_per_operation: int = DEFAULT_MAX_SCENARIOS_PER_OPERATION


@dataclass
class _Variables:
    """Variáveis de collection; credenciais sempre com valor vazio."""

    entries: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add(self, key: str, value: str = "", description: str | None = None) -> str:
        if key not in self.entries:
            entry: dict[str, Any] = {"key": key, "value": value, "type": "string"}
            if description:
                entry["description"] = description
            self.entries[key] = entry
        return "{{" + key + "}}"


@dataclass
class _Draft:
    """Requisição intermediária, alterável pelos cenários antes da renderização."""

    name: str
    method: str
    path: str
    path_values: dict[str, str] = field(default_factory=dict)
    query: list[dict[str, Any]] = field(default_factory=list)
    headers: list[dict[str, Any]] = field(default_factory=list)
    cookies: list[dict[str, Any]] = field(default_factory=list)
    content_type: str | None = None
    body: Any = None
    has_body: bool = False
    auth: dict[str, Any] | None = None
    description: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)


# --------------------------------------------------------------------- API


def generate_collection(
    spec: ApiSpec,
    *,
    operation_ids: list[str] | None = None,
    tag: str | None = None,
    method: str | None = None,
    auth_status: str | None = None,
    text: str | None = None,
    options: CollectionOptions | None = None,
) -> dict[str, Any]:
    """Gera e valida a collection para o escopo pedido. Lança erro se o resultado for inválido."""
    options = options or CollectionOptions()
    operations = _select_operations(spec, operation_ids, tag, method, auth_status, text)
    collection = _CollectionBuilder(spec, options).build(operations)
    errors = validate_collection(collection)
    if errors:
        raise CollectionGenerationError("Generated collection is invalid: " + "; ".join(errors))
    return collection


def collection_summary(collection: dict[str, Any]) -> dict[str, Any]:
    """Resumo enxuto para o modelo, sem repetir o JSON inteiro."""
    requests = list(_iter_requests(collection["item"]))
    return {
        "name": collection["info"]["name"],
        "requests": len(requests),
        "folders": [item["name"] for item in collection["item"]],
        "variables": [variable["key"] for variable in collection.get("variable", [])],
        "requests_preview": [name for name, _ in requests[:COLLECTION_PREVIEW_REQUESTS]],
    }


def write_collection(collection: dict[str, Any], output_dir: str | Path, filename: str | None = None) -> Path:
    """Grava a collection dentro de `output_dir` (nome sanitizado, sem sair do diretório)."""
    directory = Path(output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    stem = _UNSAFE_FILENAME.sub("_", Path(filename or collection["info"]["name"]).stem).strip("._") or "collection"
    target = (directory / f"{stem}.postman_collection.json").resolve()
    if target.parent != directory:
        raise CollectionGenerationError("Invalid file name.")
    target.write_text(json.dumps(collection, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _select_operations(spec: ApiSpec, operation_ids: list[str] | None, tag: str | None, method: str | None,
                       auth_status: str | None, text: str | None) -> list[Operation]:
    if operation_ids:
        selected = [get_operation(spec, identifier) for identifier in operation_ids]
        filtered = {id(op) for op in filter_operations(spec, tag=tag, method=method, auth_status=auth_status,
                                                       text=text)}
        selected = [op for op in selected if id(op) in filtered]
    else:
        selected = filter_operations(spec, tag=tag, method=method, auth_status=auth_status, text=text)
    if not selected:
        raise CollectionGenerationError("No operation matches the requested scope.")
    return selected


def _iter_requests(items: list[dict[str, Any]]):
    for item in items:
        if "request" in item:
            yield item["name"], item
        else:
            yield from _iter_requests(item.get("item", []))


# ----------------------------------------------------------------- builder


class _CollectionBuilder:
    def __init__(self, spec: ApiSpec, options: CollectionOptions) -> None:
        self.spec = spec
        self.options = options
        self.resolver = RefResolver(spec.document)
        self.examples = ExampleBuilder(self.resolver)
        self.variables = _Variables()

    def build(self, operations: list[Operation]) -> dict[str, Any]:
        self._add_base_url()
        folders: dict[str, list[dict[str, Any]]] = {}
        for operation in operations:
            folder = folders.setdefault(_folder_name(operation), [])
            draft = self._base_draft(operation)
            folder.append(_render_item(draft))
            if self.options.include_scenarios:
                scenarios = self._scenario_items(operation, draft)
                if scenarios:
                    folder.append({"name": f"Scenarios: {draft.name}", "item": scenarios})
        collection: dict[str, Any] = {
            "info": {
                "_postman_id": str(uuid.uuid4()),
                "name": self.options.name or self.spec.title or "API",
                "description": self._collection_description(),
                "schema": POSTMAN_SCHEMA_URL,
            },
            "item": [{"name": name, "item": items} for name, items in folders.items()],
        }
        if self.variables.entries:
            collection["variable"] = list(self.variables.entries.values())
        return collection

    def _collection_description(self) -> str:
        return (
            f"Generated by veriq from '{self.spec.source_name}' "
            f"({'Swagger' if self.spec.version.value == '2.0' else 'OpenAPI'} {self.spec.version_string}). "
            "The requests were NOT executed. Fill in the credential variables before use. "
            "Values marked as suggested are not in the specification."
        )

    def _add_base_url(self) -> None:
        servers = self.spec.servers
        if not servers:
            self.variables.add(BASE_URL_VARIABLE, "", "No server declared; set the base URL.")
            return
        server = servers[0]
        url = _PATH_TEMPLATE.sub(lambda match: _server_variable_default(server.variables, match.group(1)), server.url)
        note = "First declared server."
        if len(servers) > 1:
            note += " Alternatives: " + ", ".join(item.url for item in servers[1:])
        if not re.match(r"^[a-z][a-z0-9+.-]*://", url):
            note += " Relative URL or no protocol: adjust for your environment."
        self.variables.add(BASE_URL_VARIABLE, url.rstrip("/"), note)

    # ------------------------------------------------------- requisição base

    def _base_draft(self, operation: Operation) -> _Draft:
        plan_request = plan_operation_tests(self.spec, operation.key, max_scenarios=0)["valid_request"]
        draft = _Draft(name=operation.summary or operation.key, method=operation.method.upper(), path=operation.path)
        if operation.description:
            draft.description.append(operation.description)
        draft.description.append(f"Operation: {operation.key}" +
                                 (f" (operationId: {operation.operation_id})" if operation.operation_id else ""))
        for parameter in operation.parameters:
            self._add_parameter(draft, parameter, plan_request)
        if "content_type" in plan_request:
            draft.content_type = plan_request["content_type"]
            draft.body = plan_request.get("body")
            draft.has_body = True
        suggested = sorted(key for key, origin in plan_request.get("value_origins", {}).items() if origin == SUGGESTED)
        if suggested:
            draft.description.append("Values suggested by veriq (not documented): " + ", ".join(suggested) + ".")
        security = analyze_operation_security(self.spec, operation)
        draft.auth = self._auth(security, draft)
        if self.options.include_tests:
            draft.tests = self._success_tests(operation)
        return draft

    def _add_parameter(self, draft: _Draft, parameter: Parameter, plan_request: dict[str, Any]) -> None:
        if parameter.location == "header" and parameter.name.lower() in _IGNORED_HEADER_PARAMETERS:
            return
        if parameter.required and parameter.name in plan_request.get(parameter.location, {}):
            value = plan_request[parameter.location][parameter.name]
        elif parameter.has_example:
            value = parameter.example
        else:
            value, _ = self.examples.build(parameter.schema or {"type": "string"})
        entry = {"key": parameter.name, "value": _to_text(value), "disabled": not parameter.required}
        if parameter.description:
            entry["description"] = parameter.description
        if parameter.location == "path":
            draft.path_values[parameter.name] = entry["value"]
        elif parameter.location == "query":
            draft.query.append(entry)
        elif parameter.location == "header":
            draft.headers.append(entry)
        elif parameter.location == "cookie":
            draft.cookies.append(entry)

    # ------------------------------------------------------------ autenticação

    def _auth(self, security: OperationSecurity, draft: _Draft) -> dict[str, Any] | None:
        if security.status is AuthStatus.INDETERMINATE:
            draft.description.append("Security is indeterminate in the specification: configure authentication "
                                     "manually. " + " ".join(security.notes))
            return None
        if security.status is AuthStatus.NONE_DECLARED:
            if security.optional:
                draft.description.append("Authentication declared as optional.")
            return {"type": "noauth"}
        if len(security.alternatives) > 1:
            others = [" + ".join(usage.name for usage in alternative) for alternative in security.alternatives[1:]]
            draft.description.append("Declared authentication alternatives not applied: " + "; ".join(others) + ".")
        auth: dict[str, Any] | None = None
        for usage in security.alternatives[0]:
            scheme = self.spec.security_schemes[usage.name]
            if auth is None:
                auth = self._postman_auth(scheme, usage.scopes, draft)
            else:
                self._extra_credential(scheme, draft)
        return auth

    def _postman_auth(self, scheme: SecurityScheme, scopes: list[str], draft: _Draft) -> dict[str, Any] | None:
        ident = _identifier(scheme.name)
        if scheme.type == "http" and scheme.scheme == "bearer":
            token = self.variables.add(f"{ident}Token", description=f"Bearer token for '{scheme.name}'.")
            return {"type": "bearer", "bearer": [_attr("token", token)]}
        if scheme.type == "http" and scheme.scheme in ("basic", "digest"):
            username = self.variables.add(f"{ident}Username", description=f"Username for '{scheme.name}'.")
            password = self.variables.add(f"{ident}Password", description=f"Password for '{scheme.name}'.")
            return {"type": scheme.scheme, scheme.scheme: [_attr("username", username), _attr("password", password)]}
        if scheme.type == "apiKey" and scheme.location in ("header", "query"):
            value = self.variables.add(f"{ident}ApiKey", description=f"API key '{scheme.parameter_name}'.")
            return {"type": "apikey", "apikey": [_attr("key", scheme.parameter_name or ""), _attr("value", value),
                                                 _attr("in", scheme.location)]}
        if scheme.type == "apiKey" and scheme.location == "cookie":
            self._extra_credential(scheme, draft)
            return {"type": "noauth"}
        if scheme.type in ("oauth2", "openIdConnect"):
            return self._oauth2(scheme, scopes, ident)
        draft.description.append(f"Scheme '{scheme.name}' ({scheme.type}) cannot be represented in Postman; "
                                 "configure it manually.")
        return None

    def _oauth2(self, scheme: SecurityScheme, scopes: list[str], ident: str) -> dict[str, Any]:
        token = self.variables.add(f"{ident}AccessToken", description=f"Access token for '{scheme.name}'.")
        attributes = [_attr("accessToken", token), _attr("addTokenTo", "header")]
        if scheme.flows:
            flow_name, flow = next(iter(scheme.flows.items()))
            if flow_name in _OAUTH_GRANT_TYPES:
                attributes.append(_attr("grant_type", _OAUTH_GRANT_TYPES[flow_name]))
            if isinstance(flow, dict):
                for source, target in (("authorizationUrl", "authUrl"), ("tokenUrl", "accessTokenUrl")):
                    if isinstance(flow.get(source), str):
                        attributes.append(_attr(target, flow[source]))
            attributes.append(_attr("clientId", self.variables.add(f"{ident}ClientId")))
            attributes.append(_attr("clientSecret", self.variables.add(f"{ident}ClientSecret")))
        if scopes:
            attributes.append(_attr("scope", " ".join(scopes)))
        return {"type": "oauth2", "oauth2": attributes}

    def _extra_credential(self, scheme: SecurityScheme, draft: _Draft) -> None:
        """Credenciais adicionais (AND) de API key viram header/query/cookie com variável."""
        if scheme.type != "apiKey" or not scheme.parameter_name:
            draft.description.append(f"Credencial adicional '{scheme.name}' exigida; configure manualmente.")
            return
        value = self.variables.add(f"{_identifier(scheme.name)}ApiKey",
                                   description=f"API key '{scheme.parameter_name}'.")
        entry = {"key": scheme.parameter_name, "value": value, "disabled": False}
        {"header": draft.headers, "query": draft.query, "cookie": draft.cookies}.get(
            scheme.location or "header", draft.headers).append(entry)

    # ------------------------------------------------------------------ testes

    def _success_tests(self, operation: Operation) -> list[str]:
        success = [response for response in operation.responses if response.status_code.startswith("2")]
        if not success:
            return ["// No documented 2xx response: no status assertion was generated."]
        explicit = [int(response.status_code) for response in success if response.status_code.isdigit()]
        if explicit:
            codes = ", ".join(str(code) for code in explicit)
            lines = [f'pm.test("Documented status ({codes})", function () {{',
                     f"    pm.expect(pm.response.code).to.be.oneOf([{codes}]);", "});"]
        else:
            lines = ['pm.test("Documented 2XX status", function () {',
                     "    pm.expect(pm.response.code).to.be.within(200, 299);", "});"]
        for response in success:
            if response.status_code.isdigit():
                lines.extend(self._response_body_tests(response))
        return lines

    def _response_body_tests(self, response: Response) -> list[str]:
        if len(response.content) != 1:
            return []
        media = response.content[0]
        code = response.status_code
        body: list[str] = [
            f'    pm.test("Documented Content-Type ({code})", function () {{',
            f'        pm.expect(pm.response.headers.get("Content-Type") || "").to.include({json.dumps(media.content_type)});',
            "    });",
        ]
        if "json" in media.content_type and media.schema is not None:
            schema = self.resolver.inline(media.schema)
            properties, required = object_view(schema) if isinstance(schema, dict) else ({}, [])
            if required and (schema.get("type") in (None, "object") or properties):
                body += [
                    f'    pm.test("Documented required fields ({code})", function () {{',
                    "        const body = pm.response.json();",
                    f"        {json.dumps(required)}.forEach(function (field) {{",
                    "            pm.expect(body).to.have.property(field);",
                    "        });",
                    "    });",
                ]
        return [f"if (pm.response.code === {code}) {{"] + body + ["}"]

    # ----------------------------------------------------------------- cenários

    def _scenario_items(self, operation: Operation, base: _Draft) -> list[dict[str, Any]]:
        plan = plan_operation_tests(self.spec, operation.key, max_scenarios=self.options.max_scenarios_per_operation)
        items = []
        for scenario in plan["scenarios"]:
            if scenario["category"] == "positive" and "add_optional_parameters" not in scenario["inputs"]:
                continue  # já representado pela requisição base
            items.append(_render_item(_apply_scenario(base, scenario)))
        return items


# ------------------------------------------------------------------ cenários


def _apply_scenario(base: _Draft, scenario: dict[str, Any]) -> _Draft:
    draft = copy.deepcopy(base)
    inputs = scenario["inputs"]
    draft.name = f"[{scenario['id']}] {scenario['description']}"
    draft.description = [f"Scenario {scenario['id']} ({scenario['category']}, basis: {scenario['basis']}).",
                         *scenario.get("notes", [])]
    if "trigger" in inputs:
        draft.description.append(f"Trigger: {inputs['trigger']}.")

    auth_mode = inputs.get("auth")
    if auth_mode == "omitted":
        draft.auth = {"type": "noauth"}
    elif auth_mode == "invalid":
        draft.auth = _invalidate_auth(draft.auth)
    elif auth_mode == "missing_scopes":
        draft.description.append("Use a valid credential that lacks the required scopes.")

    if "body" in inputs and inputs["body"] is None:
        draft.has_body, draft.body, draft.content_type = False, None, None
    if "body_remove" in inputs and isinstance(draft.body, dict):
        draft.body.pop(inputs["body_remove"], None)
    if "body_set" in inputs:
        draft.body = {**(draft.body if isinstance(draft.body, dict) else {}), **inputs["body_set"]}
    if "content_type" in inputs:
        draft.content_type = inputs["content_type"]
        draft.body = "plain text"
    if "parameter" in inputs:
        _apply_parameter(draft, inputs)
    if "add_optional_parameters" in inputs:
        for entry in draft.query + draft.headers + draft.cookies:
            entry["disabled"] = False

    draft.tests = _scenario_tests(scenario)
    return draft


def _apply_parameter(draft: _Draft, inputs: dict[str, Any]) -> None:
    name, location = inputs["parameter"], inputs["in"]
    if location == "path":
        if "value" in inputs:
            draft.path_values[name] = _to_text(inputs["value"])
        return
    entries = {"query": draft.query, "header": draft.headers, "cookie": draft.cookies}.get(location, [])
    for entry in list(entries):
        if entry["key"] != name:
            continue
        if inputs.get("action") == "omit":
            entries.remove(entry)
        else:
            entry["value"], entry["disabled"] = _to_text(inputs.get("value")), False


def _invalidate_auth(auth: dict[str, Any] | None) -> dict[str, Any] | None:
    if not auth or auth.get("type") in (None, "noauth"):
        return auth
    invalid = copy.deepcopy(auth)
    for attribute in invalid.get(invalid["type"], []):
        if attribute["key"] in ("token", "password", "accessToken") or (
                invalid["type"] == "apikey" and attribute["key"] == "value"):
            attribute["value"] = INVALID_CREDENTIAL
    return invalid


def _scenario_tests(scenario: dict[str, Any]) -> list[str]:
    status = scenario["expected"]["status"]
    label = json.dumps(f"[{scenario['id']}]")[1:-1]
    if scenario["basis"] == "documented" and isinstance(status, list) and all(code.isdigit() for code in status):
        codes = ", ".join(status)
        return [f'pm.test("{label} Documented status ({codes})", function () {{',
                f"    pm.expect(pm.response.code).to.be.oneOf([{codes}]);", "});"]
    return [f"// Hypothesis: the expected status is not documented in the specification ({status}).",
            f'pm.test.skip("{label} Hypothesis without documented status", function () {{}});']


# ------------------------------------------------------------------- render


def _render_item(draft: _Draft) -> dict[str, Any]:
    request: dict[str, Any] = {
        "method": draft.method,
        "header": _render_headers(draft),
        "url": _render_url(draft),
    }
    if draft.has_body:
        request["body"] = _render_body(draft.content_type, draft.body)
    if draft.auth is not None:
        request["auth"] = draft.auth
    if draft.description:
        request["description"] = "\n\n".join(draft.description)
    item: dict[str, Any] = {"name": draft.name, "request": request}
    if draft.tests:
        item["event"] = [{"listen": "test", "script": {"type": "text/javascript", "exec": draft.tests}}]
    return item


def _render_headers(draft: _Draft) -> list[dict[str, Any]]:
    headers = [_kv(entry) for entry in draft.headers]
    if draft.has_body and draft.content_type and not draft.content_type.startswith("multipart/"):
        headers.append({"key": "Content-Type", "value": draft.content_type})
    enabled_cookies = [f"{entry['key']}={entry['value']}" for entry in draft.cookies if not entry.get("disabled")]
    if enabled_cookies:
        headers.append({"key": "Cookie", "value": "; ".join(enabled_cookies)})
    return headers


def _render_url(draft: _Draft) -> dict[str, Any]:
    segments: list[str] = []
    variables = []
    for segment in draft.path.strip("/").split("/"):
        if not segment:
            continue
        match = _PATH_SEGMENT_VARIABLE.match(segment)
        if match:
            name = match.group(1)
            segments.append(f":{name}")
            variables.append({"key": name, "value": draft.path_values.get(name, "")})
        else:
            segments.append(_PATH_TEMPLATE.sub(lambda m: draft.path_values.get(m.group(1), m.group(0)), segment))
    query = [_kv(entry) for entry in draft.query]
    raw = "{{" + BASE_URL_VARIABLE + "}}/" + "/".join(segments)
    enabled = [f"{entry['key']}={entry['value']}" for entry in draft.query if not entry.get("disabled")]
    if enabled:
        raw += "?" + "&".join(enabled)
    url: dict[str, Any] = {"raw": raw, "host": ["{{" + BASE_URL_VARIABLE + "}}"], "path": segments}
    if query:
        url["query"] = query
    if variables:
        url["variable"] = variables
    return url


def _render_body(content_type: str | None, body: Any) -> dict[str, Any]:
    media = (content_type or "").lower()
    if "json" in media and not isinstance(body, str):
        return {"mode": "raw", "raw": json.dumps(body, ensure_ascii=False, indent=2),
                "options": {"raw": {"language": "json"}}}
    if media == "application/x-www-form-urlencoded" and isinstance(body, dict):
        return {"mode": "urlencoded",
                "urlencoded": [{"key": key, "value": _to_text(value)} for key, value in body.items()]}
    if media.startswith("multipart/") and isinstance(body, dict):
        return {"mode": "formdata", "formdata": [_form_field(key, value) for key, value in body.items()]}
    return {"mode": "raw", "raw": body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)}


def _form_field(key: str, value: Any) -> dict[str, Any]:
    if value is None:
        return {"key": key, "type": "file", "src": []}  # arquivo a ser selecionado pelo usuário
    return {"key": key, "value": _to_text(value), "type": "text"}


def _kv(entry: dict[str, Any]) -> dict[str, Any]:
    rendered = {"key": entry["key"], "value": entry["value"]}
    if entry.get("disabled"):
        rendered["disabled"] = True
    if entry.get("description"):
        rendered["description"] = entry["description"]
    return rendered


# ------------------------------------------------------------------ helpers


def _folder_name(operation: Operation) -> str:
    if operation.tags:
        return operation.tags[0]
    segment = next((part for part in operation.path.split("/") if part and not part.startswith("{")), "")
    return segment or "root"


def _server_variable_default(variables: dict[str, Any], name: str) -> str:
    variable = variables.get(name)
    if isinstance(variable, dict) and "default" in variable:
        return str(variable["default"])
    return "{{" + name + "}}"


def _identifier(name: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", name) if part]
    if not parts:
        return "auth"
    return parts[0][0].lower() + parts[0][1:] + "".join(part[0].upper() + part[1:] for part in parts[1:])


def _attr(key: str, value: str) -> dict[str, str]:
    return {"key": key, "value": value, "type": "string"}


def _to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False)
