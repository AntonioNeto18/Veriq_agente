"""Carregamento seguro de arquivos OpenAPI (JSON/YAML) e detecção de versão.

O conteúdo é tratado como entrada não confiável: há limite de tamanho, de
aliases YAML, de profundidade e de quantidade de nós, e somente o carregador
seguro do PyYAML é utilizado. Nenhuma referência externa é acessada aqui.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from ..config import MAX_DOCUMENT_DEPTH, MAX_DOCUMENT_NODES, MAX_YAML_ALIASES, max_spec_bytes
from .models import SpecVersion

_JSON_SUFFIXES = {".json"}
_YAML_SUFFIXES = {".yaml", ".yml"}
_VERSION_PATTERNS: dict[SpecVersion, re.Pattern[str]] = {
    SpecVersion.OPENAPI_3_0: re.compile(r"^3\.0(\.\d+)?$"),
    SpecVersion.OPENAPI_3_1: re.compile(r"^3\.1(\.\d+)?$"),
}


class SpecLoadError(Exception):
    """Erro de leitura, parsing ou versão não suportada, com mensagem para o usuário."""

    def __init__(self, message: str, *, line: int | None = None, column: int | None = None) -> None:
        location = f" (line {line}, column {column})" if line is not None else ""
        super().__init__(f"{message}{location}")
        self.line = line
        self.column = column


@dataclass(frozen=True)
class LoadedDocument:
    document: dict[str, Any]
    format: str  # "json" | "yaml"
    source_name: str
    version: SpecVersion
    version_string: str


def load_spec_file(path: str | Path, *, max_bytes: int | None = None) -> LoadedDocument:
    """Lê um arquivo local, faz o parsing e identifica a versão da especificação."""
    file_path = Path(path)
    limit = max_bytes if max_bytes is not None else max_spec_bytes()
    if not file_path.is_file():
        raise SpecLoadError(f"File not found or not a regular file: {file_path.name}")
    if file_path.stat().st_size > limit:
        raise SpecLoadError(f"File exceeds the {limit}-byte limit: {file_path.name}")
    with file_path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise SpecLoadError(f"File exceeds the {limit}-byte limit: {file_path.name}")
    return load_spec_bytes(data, source_name=file_path.name, format_hint=_format_from_suffix(file_path))


def load_spec_text(
    text: str, *, source_name: str = "<texto>", format_hint: str | None = None, max_bytes: int | None = None
) -> LoadedDocument:
    """Faz o parsing de um conteúdo já em memória (útil para testes e uploads)."""
    return load_spec_bytes(text.encode("utf-8"), source_name=source_name, format_hint=format_hint, max_bytes=max_bytes)


def load_spec_bytes(
    data: bytes, *, source_name: str, format_hint: str | None = None, max_bytes: int | None = None
) -> LoadedDocument:
    limit = max_bytes if max_bytes is not None else max_spec_bytes()
    if len(data) > limit:
        raise SpecLoadError(f"Content exceeds the {limit}-byte limit: {source_name}")
    text = _decode(data, source_name)
    if not text.strip():
        raise SpecLoadError(f"Empty file: {source_name}")

    raw, detected_format = _parse(text, format_hint)
    document = _normalize(raw)
    if not isinstance(document, dict):
        raise SpecLoadError("The document root must be an object (map).")
    version, version_string = detect_version(document)
    return LoadedDocument(document, detected_format, source_name, version, version_string)


def detect_version(document: dict[str, Any]) -> tuple[SpecVersion, str]:
    """Identifica Swagger 2.0, OpenAPI 3.0 ou OpenAPI 3.1 a partir da raiz do documento."""
    if "swagger" in document:
        value = str(document["swagger"]).strip()
        if value == "2.0":
            return SpecVersion.SWAGGER_2_0, value
        raise SpecLoadError(f"Unsupported Swagger version: '{value}'. Supported: 2.0, 3.0.x and 3.1.x.")
    if "openapi" in document:
        value = str(document["openapi"]).strip()
        for version, pattern in _VERSION_PATTERNS.items():
            if pattern.match(value):
                return version, value
        raise SpecLoadError(f"Unsupported OpenAPI version: '{value}'. Supported: 2.0, 3.0.x and 3.1.x.")
    raise SpecLoadError("The document declares neither 'openapi' nor 'swagger'; it does not look like an OpenAPI specification.")


def _format_from_suffix(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in _JSON_SUFFIXES:
        return "json"
    if suffix in _YAML_SUFFIXES:
        return "yaml"
    return None


def _decode(data: bytes, source_name: str) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise SpecLoadError(f"File {source_name} is not valid UTF-8 (byte {error.start}).") from None


def _parse(text: str, format_hint: str | None) -> tuple[Any, str]:
    if format_hint == "json":
        return _parse_json(text), "json"
    if format_hint == "yaml":
        return _parse_yaml(text), "yaml"
    if text.lstrip().startswith(("{", "[")):
        try:
            return _parse_json(text), "json"
        except SpecLoadError:
            pass  # pode ser YAML em estilo de fluxo; tenta YAML abaixo
    return _parse_yaml(text), "yaml"


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise SpecLoadError(f"Invalid JSON: {error.msg}", line=error.lineno, column=error.colno) from None
    except RecursionError:
        raise SpecLoadError("JSON exceeds the maximum allowed depth.") from None


class _LimitedSafeLoader(yaml.SafeLoader):
    """SafeLoader que limita a quantidade de aliases (mitiga 'billion laughs')."""

    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self._alias_count = 0

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(yaml.AliasEvent):
            self._alias_count += 1
            if self._alias_count > MAX_YAML_ALIASES:
                raise SpecLoadError(f"YAML has too many aliases (limit: {MAX_YAML_ALIASES}).")
        return super().compose_node(parent, index)


def _parse_yaml(text: str) -> Any:
    loader = _LimitedSafeLoader(text)
    try:
        return loader.get_single_data()
    except yaml.MarkedYAMLError as error:
        mark = error.problem_mark
        problem = error.problem or "syntax error"
        if mark is None:
            raise SpecLoadError(f"Invalid YAML: {problem}") from None
        raise SpecLoadError(f"Invalid YAML: {problem}", line=mark.line + 1, column=mark.column + 1) from None
    except yaml.YAMLError as error:
        raise SpecLoadError(f"Invalid YAML: {error}") from None
    except RecursionError:
        raise SpecLoadError("YAML exceeds the maximum allowed depth.") from None
    finally:
        loader.dispose()


def _normalize(value: Any) -> Any:
    """Converte o resultado do parsing para tipos JSON, aplicando limites de profundidade e nós.

    YAML pode produzir chaves inteiras (ex.: códigos de status `200:`), datas e
    binários; tudo é convertido para strings para manter o modelo serializável.
    """
    _check_expanded_size(value)

    def walk(node: Any, depth: int) -> Any:
        if isinstance(node, dict):
            return {_normalize_key(key): walk(item, depth + 1) for key, item in node.items()}
        if isinstance(node, (list, tuple)):
            return [walk(item, depth + 1) for item in node]
        if isinstance(node, set):
            return [walk(item, depth + 1) for item in sorted(node, key=str)]
        if isinstance(node, (datetime, date)):
            return node.isoformat()
        if isinstance(node, bytes):
            return base64.b64encode(node).decode("ascii")
        return node

    return walk(value, 0)


def _check_expanded_size(value: Any) -> None:
    """Calcula o total de nós após expandir aliases YAML, sem materializar a expansão.

    Nós compartilhados por aliases são contados uma vez por referência via
    memoização, então um documento "billion laughs" é rejeitado sem custo alto.
    """
    sizes: dict[int, int] = {}

    def size(node: Any, depth: int) -> int:
        if depth > MAX_DOCUMENT_DEPTH:
            raise SpecLoadError(f"Document exceeds the maximum depth of {MAX_DOCUMENT_DEPTH} levels.")
        if not isinstance(node, (dict, list, tuple, set)):
            return 1
        if id(node) in sizes:
            return sizes[id(node)]
        children = node.values() if isinstance(node, dict) else node
        total = 1 + sum(size(child, depth + 1) for child in children)
        if total > MAX_DOCUMENT_NODES:
            raise SpecLoadError(f"Document exceeds the limit of {MAX_DOCUMENT_NODES} nodes.")
        sizes[id(node)] = total
        return total

    size(value, 0)


def _normalize_key(key: Any) -> str:
    if isinstance(key, str):
        return key
    if key is None:
        return "null"
    if isinstance(key, bool):
        return "true" if key else "false"
    if isinstance(key, (datetime, date)):
        return key.isoformat()
    return str(key)
