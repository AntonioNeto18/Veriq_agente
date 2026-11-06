#!/usr/bin/env python3
"""Builds the agent-agnostic skill packages (e.g. for Agensi) from agent_veriq.

    python packaging/build.py

Creates packaging/dist/<skill>/ and packaging/dist/<skill>.zip for each edition.
The packages contain a copy of agent_veriq/core and tools (no Google ADK) plus a CLI.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EDITIONS = {
    "openapi-explainer": {"full": False},
    "openapi-test-suite-pro": {"full": True},
}
PRO_ONLY = ["core/test_planner.py", "core/postman_generator.py", "core/postman_validator.py",
            "tools/test_planning_tools.py", "tools/postman_tools.py", "schemas"]
COMMON_IMPORT = "from ..core.postman_generator import CollectionGenerationError\n"


def vendor(source: Path, target: Path, full: bool) -> None:
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "agent.py", "skills", "*.pyc"))
    (target / "__init__.py").write_text('"""Vendored veriq core (no Google ADK dependency, no network access)."""\n')
    (target / "tools" / "__init__.py").write_text('"""CLI-facing tool functions. None of them sends HTTP requests."""\n')
    if not full:
        for rel in PRO_ONLY:
            path = target / rel
            shutil.rmtree(path) if path.is_dir() else path.unlink()
    common = target / "tools" / "_common.py"
    text = common.read_text()
    assert COMMON_IMPORT in text, "tools/_common.py changed; update build.py"
    common.write_text(text.replace(COMMON_IMPORT,
        "try:\n    from ..core.postman_generator import CollectionGenerationError\n"
        "except ImportError:  # free edition ships without the Postman generator\n"
        "    class CollectionGenerationError(Exception):\n        pass\n"))


def main() -> None:
    source = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else HERE.parent / "agent_veriq"
    dist = HERE / "dist"
    shutil.rmtree(dist, ignore_errors=True)
    for name, opts in EDITIONS.items():
        root = dist / name
        (root / "scripts").mkdir(parents=True)
        shutil.copy(HERE / "skills" / name / "SKILL.md", root / "SKILL.md")
        refs = HERE / "skills" / name / "references"
        if refs.exists():
            shutil.copytree(refs, root / "references")
        shutil.copy(HERE / "veriq.py", root / "scripts" / "veriq.py")
        vendor(source, root / "scripts" / "veriq_lib", opts["full"])
        shutil.make_archive(str(dist / name), "zip", root_dir=dist, base_dir=name)
        print("built", dist / f"{name}.zip")


if __name__ == "__main__":
    main()
