"""Tests d'architecture (Mission 1 : interdiction des dependances interdites).

Ces tests ne verifient pas le style, ils verifient des **interdictions** :

* une couche ne peut pas importer une couche superieure ;
* aucune dependance circulaire ;
* aucun module n'importe une bibliotheque de reseau ou un SDK broker ;
* chaque module public porte une docstring.

Ils sont executes par la CI : une violation architecturale casse la
construction, elle n'est pas detectee a la revue.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "etatmajor"

# Ordre des couches : une couche n'importe que les couches qui la precedent.
LAYERS = [
    "core",
    "version",
    "data",
    "execution",
    "risk",
    "challenge",
    "strategies",
    "sniper",
    "replay",
    "reporting",
    "cli",
]

FORBIDDEN_IMPORTS = {
    "socket",
    "requests",
    "urllib",
    "urllib3",
    "http",
    "httpx",
    "aiohttp",
    "MetaTrader5",
    "pandas",
    "numpy",
}


def module_files() -> list[Path]:
    return sorted(p for p in PACKAGE_ROOT.rglob("*.py"))


def layer_of(path: Path) -> str:
    """Couche d'appartenance d'un module.

    Un module situe a la racine du package (``cli.py``, ``version.py``) forme
    sa propre couche ; le ``__init__`` du package appartient a la couche de
    base.
    """
    relative = path.relative_to(PACKAGE_ROOT)
    if len(relative.parts) == 1:
        stem = relative.stem
        return "core" if stem == "__init__" else stem
    return relative.parts[0]


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
    return found


def test_the_package_is_not_empty():
    assert len(module_files()) >= 15


@pytest.mark.parametrize("path", module_files(), ids=lambda p: p.name)
def test_every_module_has_a_docstring(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assert ast.get_docstring(tree), f"{path} has no module docstring"


@pytest.mark.parametrize("path", module_files(), ids=lambda p: p.name)
def test_no_module_imports_a_forbidden_library(path: Path):
    for imported in imported_modules(path):
        root = imported.split(".")[0]
        assert root not in FORBIDDEN_IMPORTS, f"{path} imports {imported}"


@pytest.mark.parametrize("path", module_files(), ids=lambda p: p.name)
def test_no_module_imports_a_higher_layer(path: Path):
    own_layer = layer_of(path)
    own_index = LAYERS.index(own_layer)
    for imported in imported_modules(path):
        if not imported.startswith("etatmajor"):
            continue
        target_layer = imported.split(".")[1] if "." in imported else ""
        if target_layer not in LAYERS:
            continue
        target_index = LAYERS.index(target_layer)
        assert target_index <= own_index, (
            f"{path} (couche {own_layer}) importe {imported} "
            f"(couche {target_layer}) : dependance interdite"
        )


def test_no_circular_dependency():
    graph: dict[str, set[str]] = {}
    for path in module_files():
        name = ".".join(path.relative_to(PACKAGE_ROOT).with_suffix("").parts)
        if name.endswith(".__init__"):
            name = name[: -len(".__init__")]
        graph.setdefault(name, set())
        for imported in imported_modules(path):
            if imported.startswith("etatmajor"):
                graph[name].add(imported)

    state: dict[str, int] = {}
    cycles: list[list[str]] = []

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

    assert not cycles, f"circular dependencies: {cycles}"


def test_the_layer_order_is_the_documented_one():
    assert LAYERS.index("core") < LAYERS.index("data")
    assert LAYERS.index("data") < LAYERS.index("execution")
    assert LAYERS.index("execution") < LAYERS.index("risk")
    assert LAYERS.index("risk") < LAYERS.index("challenge")
    assert LAYERS.index("challenge") < LAYERS.index("strategies")
    assert LAYERS.index("strategies") < LAYERS.index("sniper")
    assert LAYERS.index("sniper") < LAYERS.index("replay")
    assert LAYERS.index("replay") < LAYERS.index("reporting")
    assert LAYERS.index("reporting") < LAYERS.index("cli")


def test_core_does_not_depend_on_any_other_layer():
    for path in module_files():
        if layer_of(path) != "core":
            continue
        for imported in imported_modules(path):
            assert not imported.startswith("etatmajor."), (
                f"{path} (couche core) ne doit importer aucune autre couche"
            )
