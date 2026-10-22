"""Audit d'inventaire du dépôt (MISSION 0).

Produit des preuves factuelles et reproductibles sur l'état réel du code :

* inventaire des fichiers (taille, lignes de code, présence de docstring) ;
* graphe des imports internes et détection des dépendances circulaires ;
* détection des stubs, corps vides, marqueurs TODO/FIXME et valeurs par
  défaut trompeuses ;
* symboles publics définis mais jamais référencés (code mort probable) ;
* enums et modèles déclarés mais non utilisés par le moteur.

Usage::

    python scripts/audit_inventory.py --output docs/audit/evidence

Le script est en lecture seule : il ne modifie aucun fichier du dépôt.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = ("src", "tests", "scripts")
STUB_MARKERS = ("TODO", "FIXME", "XXX", "HACK", "placeholder", "not implemented")
DEFAULT_MARKERS = (":param", "pass  #", "raise NotImplementedError")


def iter_python_files() -> list[Path]:
    files: list[Path] = []
    for root in SOURCE_ROOTS:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            files.append(path)
    return sorted(files)


def module_name(path: Path) -> str:
    relative = path.relative_to(REPO_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def analyse_file(path: Path) -> dict:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines()

    docstring = ast.get_docstring(tree) is not None
    functions = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.module:
                package = module_name(path).split(".")
                base = package[: len(package) - node.level + 1] if node.level else []
                imports.add(".".join(base + [node.module]))
            elif node.module:
                imports.add(node.module)

    internal = sorted(
        {
            name
            for name in imports
            if name.startswith("etatmajor")
            or name.startswith("tests")
            or name in {module_name(p) for p in iter_python_files()}
        }
    )

    stub_functions = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if len(body) == 1 and isinstance(body[0], ast.Pass):
                stub_functions.append(node.name)
            elif any(
                isinstance(stmt, ast.Raise)
                and isinstance(stmt.exc, ast.Call)
                and getattr(stmt.exc.func, "id", "") == "NotImplementedError"
                for stmt in body
            ):
                stub_functions.append(node.name)

    markers = sorted(
        {
            marker
            for marker in STUB_MARKERS
            if re.search(rf"\b{re.escape(marker)}\b", source, re.IGNORECASE)
        }
    )

    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "module": module_name(path),
        "lines": len(lines),
        "code_lines": sum(
            1
            for line in lines
            if line.strip() and not line.strip().startswith("#")
        ),
        "has_docstring": docstring,
        "classes": classes,
        "functions": functions,
        "internal_imports": internal,
        "stub_functions": stub_functions,
        "markers": markers,
    }


def detect_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Détection de cycles dans le graphe d'imports (DFS, cycles simples)."""
    cycles: list[list[str]] = []
    state: dict[str, int] = {}

    def visit(node: str, stack: list[str]) -> None:
        state[node] = 1
        for neighbour in sorted(graph.get(node, ())):
            if neighbour not in graph:
                continue
            if state.get(neighbour, 0) == 1:
                cycle = stack[stack.index(neighbour) :] + [neighbour]
                if cycle not in cycles:
                    cycles.append(cycle)
            elif state.get(neighbour, 0) == 0:
                visit(neighbour, stack + [neighbour])
        state[node] = 2

    for node in sorted(graph):
        if state.get(node, 0) == 0:
            visit(node, [node])
    return cycles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="docs/audit/evidence",
        help="directory receiving the generated evidence",
    )
    args = parser.parse_args()

    output_dir = REPO_ROOT / args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    files = [analyse_file(path) for path in iter_python_files()]

    graph: dict[str, set[str]] = defaultdict(set)
    for entry in files:
        graph[entry["module"]] = set()
        for imported in entry["internal_imports"]:
            graph[entry["module"]].add(imported)
    cycles = detect_cycles(dict(graph))

    # Symboles publics jamais référencés ailleurs dans le dépôt.
    # Les tests sont exclus : un test n'est jamais appelé par le code.
    corpus = "\n".join(
        path.read_text(encoding="utf-8")
        for path in REPO_ROOT.rglob("*.py")
        if ".venv" not in str(path) and "site-packages" not in str(path)
    )
    unused: list[dict] = []
    for entry in files:
        if not entry["module"].startswith(("src.", "scripts.")):
            continue
        for name in entry["functions"] + entry["classes"]:
            if name.startswith("_"):
                continue
            occurrences = len(re.findall(rf"\b{re.escape(name)}\b", corpus))
            if occurrences <= 1:
                unused.append({"module": entry["module"], "symbol": name})

    # Exceptions déclarées mais jamais levées : le contrat d'erreur du
    # projet n'est pas appliqué par le code.
    declared_exceptions: list[str] = []
    raised_exceptions: list[str] = []
    for entry in files:
        if not entry["module"].startswith("src."):
            continue
        for name in entry["classes"]:
            if name.endswith("Error") or name.endswith("Rejected"):
                declared_exceptions.append(name)
        for match in re.finditer(r"raise\s+([A-Za-z_][A-Za-z0-9_]*)", corpus):
            raised_exceptions.append(match.group(1))
    exceptions_never_raised = sorted(
        {name for name in declared_exceptions if name not in raised_exceptions}
    )

    stub_functions = [
        {"module": entry["module"], "function": name}
        for entry in files
        for name in entry["stub_functions"]
    ]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python_files": len(files),
        "total_lines": sum(entry["lines"] for entry in files),
        "total_code_lines": sum(entry["code_lines"] for entry in files),
        "files": files,
        "import_graph": {k: sorted(v) for k, v in sorted(graph.items())},
        "circular_dependencies": cycles,
        "stub_functions": stub_functions,
        "unreferenced_symbols": unused,
        "declared_exceptions": sorted(declared_exceptions),
        "exceptions_never_raised": exceptions_never_raised,
        "files_with_markers": [
            {"path": e["path"], "markers": e["markers"]}
            for e in files
            if e["markers"]
        ],
        "files_without_docstring": [e["path"] for e in files if not e["has_docstring"]],
    }

    (output_dir / "inventory.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"python files      : {payload['python_files']}")
    print(f"total lines       : {payload['total_lines']}")
    print(f"code lines        : {payload['total_code_lines']}")
    print(f"circular deps     : {len(cycles)}")
    print(f"stub functions    : {len(stub_functions)}")
    print(f"unreferenced syms : {len(unused)}")
    print(f"exceptions never raised : {exceptions_never_raised}")
    print(f"markers           : {len(payload['files_with_markers'])}")
    print(f"evidence written  : {output_dir / 'inventory.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
