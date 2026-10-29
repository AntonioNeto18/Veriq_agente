"""Guarda: o agente é analítico e não pode conter clientes HTTP ou de rede."""

import ast
from pathlib import Path

FORBIDDEN_MODULES = {"requests", "httpx", "aiohttp", "urllib3", "urllib.request", "http.client", "socket"}
PACKAGE_DIR = Path(__file__).parent.parent / "agent_veriq"


def _imported_modules(source: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_project_does_not_import_network_clients():
    offenders = {}
    for path in PACKAGE_DIR.rglob("*.py"):
        found = {
            module for module in _imported_modules(path.read_text(encoding="utf-8"))
            if any(module == banned or module.startswith(f"{banned}.") for banned in FORBIDDEN_MODULES)
        }
        if found:
            offenders[str(path.relative_to(PACKAGE_DIR))] = sorted(found)
    assert offenders == {}
