"""Registro em memória das especificações já processadas.

As ferramentas do agente consultam recortes da `ApiSpec` armazenada aqui, sem
reprocessar o arquivo nem enviar o documento inteiro ao modelo.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from .models import ApiSpec
from .openapi_loader import LoadedDocument, load_spec_file
from .openapi_parser import parse_spec


class SpecNotLoadedError(LookupError):
    """Nenhuma especificação carregada (ou id desconhecido)."""


class SpecStore:
    def __init__(self) -> None:
        self._specs: dict[str, ApiSpec] = {}
        self._active_id: str | None = None
        self._lock = threading.Lock()

    def load_file(self, path: str | Path) -> tuple[str, ApiSpec]:
        """Carrega, normaliza e registra um arquivo; ele passa a ser a especificação ativa."""
        return self.register(load_spec_file(path))

    def register(self, loaded: LoadedDocument) -> tuple[str, ApiSpec]:
        spec = parse_spec(loaded)
        spec_id = _spec_id(loaded)
        with self._lock:
            self._specs[spec_id] = spec
            self._active_id = spec_id
        return spec_id, spec

    def get(self, spec_id: str | None = None) -> ApiSpec:
        """Retorna a especificação indicada ou, sem id, a ativa."""
        with self._lock:
            wanted = spec_id or self._active_id
            if wanted is None or wanted not in self._specs:
                raise SpecNotLoadedError(
                    "Nenhuma especificação carregada." if wanted is None else f"Especificação '{wanted}' não encontrada."
                )
            return self._specs[wanted]

    def list_ids(self) -> list[str]:
        with self._lock:
            return list(self._specs)

    def clear(self) -> None:
        with self._lock:
            self._specs.clear()
            self._active_id = None


def _spec_id(loaded: LoadedDocument) -> str:
    digest = hashlib.sha256(json.dumps(loaded.document, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    stem = Path(loaded.source_name).stem or "spec"
    return f"{stem}-{digest[:8]}"


default_store = SpecStore()
