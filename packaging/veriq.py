#!/usr/bin/env python3
"""veriq: offline OpenAPI/Swagger analysis CLI for AI coding agents.

Reads a local OpenAPI 2.0/3.0/3.1 file (JSON or YAML) and prints structured JSON.
It NEVER sends HTTP requests to the API being analysed and never executes tests.

Usage:  python veriq.py <spec-file> <command> [options]
Run     python veriq.py --help   for the command list.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

AUTH_CHOICES = ["declared_required", "none_declared", "indeterminate"]


def _require_dependencies() -> None:
    missing = []
    for module, package in (("yaml", "pyyaml"), ("jsonschema", "jsonschema")):
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if missing:
        _emit({"status": "error",
               "error": f"Missing Python packages: {', '.join(missing)}. Install with: pip install {' '.join(missing)}"})
        sys.exit(2)


def _emit(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _has(module: str) -> bool:
    return (Path(__file__).resolve().parent / "veriq_lib" / "tools" / f"{module}.py").exists()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="veriq.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec", help="Path to the OpenAPI/Swagger file (.json, .yaml, .yml)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("summary", help="Version, metadata, servers, tags, counts and top problems")
    p = sub.add_parser("problems", help="Parsing errors, warnings and limitations")
    p.add_argument("--severity", choices=["error", "warning", "info"])
    p.add_argument("--limit", type=int, default=30)
    p = sub.add_parser("schemas", help="Names of reusable schemas")
    p.add_argument("--limit", type=int, default=100)
    p = sub.add_parser("schema", help="Structured summary of one schema")
    p.add_argument("name")
    p.add_argument("--depth", type=int, default=3)
    p = sub.add_parser("refs", help="External or unresolved $ref (use --all for every $ref)")
    p.add_argument("--all", action="store_true")
    p.add_argument("--limit", type=int, default=50)

    p = sub.add_parser("endpoints", help="List operations with minimal fields")
    _add_filters(p)
    p.add_argument("--limit", type=int, default=100)
    p = sub.add_parser("endpoint", help='Full contract of one operation (operationId or "METHOD /path")')
    p.add_argument("operation")

    p = sub.add_parser("auth", help="Declared authentication (overview, or one operation)")
    p.add_argument("operation", nargs="?")
    p.add_argument("--limit", type=int, default=100)
    p = sub.add_parser("auth-gaps", help="Missing or inconsistent authentication information")
    p.add_argument("--limit", type=int, default=50)

    if _has("test_planning_tools"):
        p = sub.add_parser("plan", help="Positive/negative test scenarios for one operation")
        p.add_argument("operation")
        p.add_argument("--max", type=int, default=25)
        p = sub.add_parser("plan-set", help="Test scenarios for several operations (max 10) or a tag")
        p.add_argument("--ops", nargs="+")
        p.add_argument("--tag")
        p.add_argument("--max-per-op", type=int, default=10)
    if _has("postman_tools"):
        p = sub.add_parser("postman", help="Generate a validated Postman v2.1.0 collection")
        p.add_argument("--ops", nargs="+", help='operationIds or "METHOD /path"')
        _add_filters(p)
        p.add_argument("--name")
        p.add_argument("--scenarios", action="store_true", help="Add folders with planned test scenarios")
        p.add_argument("--out", help="Output directory (default: ./output or $VERIQ_OUTPUT_DIR)")
        p.add_argument("--json", action="store_true", help="Also print the collection JSON")
    return parser


def _add_filters(p: argparse.ArgumentParser) -> None:
    p.add_argument("--tag")
    p.add_argument("--method")
    p.add_argument("--auth", choices=AUTH_CHOICES)
    p.add_argument("--text")


def run(args: argparse.Namespace) -> dict:
    import os
    if getattr(args, "out", None):
        os.environ["VERIQ_OUTPUT_DIR"] = args.out
    from veriq_lib.tools import endpoint_tools as ep, security_tools as sec, specification_tools as spec

    loaded = spec.carregar_especificacao(args.spec)
    if loaded["status"] != "ok" or args.command == "summary":
        return loaded

    c = args.command
    if c == "problems":
        return spec.listar_problemas_especificacao(args.severity, args.limit)
    if c == "schemas":
        return spec.listar_schemas(args.limit)
    if c == "schema":
        return spec.obter_schema(args.name, args.depth)
    if c == "refs":
        return spec.listar_referencias(not args.all, args.limit)
    if c == "endpoints":
        return ep.listar_endpoints(args.tag, args.method, args.auth, args.text, args.limit)
    if c == "endpoint":
        return ep.obter_detalhes_endpoint(args.operation)
    if c == "auth":
        return sec.analisar_autenticacao(args.operation, args.limit)
    if c == "auth-gaps":
        return sec.listar_lacunas_autenticacao(args.limit)
    if c == "plan":
        from veriq_lib.tools import test_planning_tools as tp
        return tp.planejar_testes_endpoint(args.operation, args.max)
    if c == "plan-set":
        from veriq_lib.tools import test_planning_tools as tp
        return tp.planejar_testes_conjunto(args.ops, args.tag, args.max_per_op)
    if c == "postman":
        from veriq_lib.tools import postman_tools as pm
        return pm.gerar_postman_collection(args.ops, args.tag, args.method, args.auth, args.text, args.name,
                                           args.scenarios, True, args.json)
    return {"status": "error", "error": f"Unknown command {c}"}


def main() -> int:
    args = build_parser().parse_args()
    _require_dependencies()
    result = run(args)
    _emit(result)
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
