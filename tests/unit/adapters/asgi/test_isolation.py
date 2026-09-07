"""The ASGI adapter must stay free of every web framework.

Two guards, because either alone is easy to defeat. The static one reads every import
statement in the package and refuses anything that is neither the standard library, the
package itself, nor the shared contracts. The dynamic one loads the package in a fresh
interpreter, with the ``bustan`` package replaced by an empty stand-in so that importing
the framework cannot be what satisfies an import, and asserts that no web framework and
no framework module other than the contracts ended up in ``sys.modules``.

Two imports are exempt from the static guard and named symbol by symbol below, both on
the path that reads a request body: the error the framework raises when a body is over
the limit, which the adapter has to raise by that name or a caller it refused is
answered as though the server had broken, and the reader for the limits the application
serving the request declared, which the adapter has to ask or it bounds the read by a
figure nobody chose. Each is made inside the function that uses it rather than at module
scope, so importing this package still pulls in nothing but the standard library and the
contracts - which is the property the dynamic guard measures, and it is left measuring
exactly that.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
ADAPTER_ROOT = REPOSITORY_ROOT / "src" / "bustan" / "adapters" / "asgi"

# Every standard library module the adapter is allowed to import. Adding to this list
# means the adapter took on a new dependency, which is the thing this test makes visible.
ALLOWED_ROOTS = frozenset(
    {
        "__future__",
        "asyncio",
        "collections",
        "contextlib",
        "dataclasses",
        "http",
        "io",
        "json",
        "mimetypes",
        "os",
        "pathlib",
        "re",
        "threading",
        "typing",
        "urllib",
    }
)

# The one package outside its own that the adapter may reach for: the vocabulary the
# framework and every adapter are written against.
ALLOWED_FRAMEWORK_PACKAGE = "contracts"

# What the adapter may reach for from inside a function body, and nothing else. Each
# entry is the module and the one name the adapter imports from it. An import listed
# here still costs the adapter nothing to import, because it is not made until the line
# that needs it runs; anything that wants to be imported when the package is loaded
# belongs in the two allowances above, where the dynamic guard can see it.
ALLOWED_DEFERRED_IMPORTS = frozenset(
    {
        ("...runtime.params", "RequestBodyTooLargeError"),
        ("...runtime.execution", "request_limits_of"),
    }
)

_LOAD_IN_ISOLATION = """
import importlib
import json
import pathlib
import sys
import types

source_root = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(source_root))

# An empty stand-in for the framework package, so that importing bustan itself - which
# does import a web framework - can never be what makes the adapter's imports resolve.
stand_in = types.ModuleType("bustan")
stand_in.__path__ = [str(source_root / "bustan")]
sys.modules["bustan"] = stand_in

importlib.import_module("bustan.adapters.asgi")

frameworks = {
    "aiohttp",
    "anyio",
    "django",
    "falcon",
    "fastapi",
    "flask",
    "httpx",
    "hypercorn",
    "pydantic",
    "quart",
    "sanic",
    "starlette",
    "tornado",
    "uvicorn",
    "werkzeug",
}
print(
    json.dumps(
        {
            "frameworks": sorted(n for n in sys.modules if n.split(".")[0] in frameworks),
            "framework_packages": sorted(
                n.split(".")[1]
                for n in sys.modules
                if n.startswith("bustan.") and n.count(".") >= 1
            ),
        }
    )
)
"""


def _package_modules() -> list[Path]:
    return sorted(ADAPTER_ROOT.glob("*.py"))


def _deferred_import_nodes(tree: ast.Module) -> set[int]:
    """Return the id of every import statement written inside a function body."""

    deferred: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, (ast.Import, ast.ImportFrom)):
                deferred.add(id(inner))
    return deferred


def _is_allowed_deferred_import(node: ast.Import | ast.ImportFrom) -> bool:
    """Whether one deferred import is a named exemption rather than a new dependency."""

    if isinstance(node, ast.Import):
        return False
    module = f"{'.' * node.level}{node.module or ''}"
    return all((module, alias.name) in ALLOWED_DEFERRED_IMPORTS for alias in node.names)


def _offending_import(module_path: Path, node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.Import):
        return [
            f"{module_path.name}: import {alias.name}"
            for alias in node.names
            if alias.name.split(".")[0] not in ALLOWED_ROOTS
        ]
    if node.level == 1:
        return []
    if node.level == 3 and (node.module or "").split(".")[0] == ALLOWED_FRAMEWORK_PACKAGE:
        return []
    if node.level:
        return [f"{module_path.name}: from {'.' * node.level}{node.module or ''} import ..."]
    if (node.module or "").split(".")[0] not in ALLOWED_ROOTS:
        return [f"{module_path.name}: from {node.module} import ..."]
    return []


def test_the_package_has_modules_to_check() -> None:
    assert _package_modules(), f"no modules found under {ADAPTER_ROOT}"


def test_no_module_imports_anything_but_the_standard_library_and_the_contracts() -> None:
    offenders: list[str] = []

    for module_path in _package_modules():
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        deferred = _deferred_import_nodes(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if id(node) in deferred and _is_allowed_deferred_import(node):
                continue
            offenders.extend(_offending_import(module_path, node))

    assert offenders == []


def test_the_exempt_deferred_imports_are_the_only_ones_and_are_still_made() -> None:
    """The exemption is worth nothing if it stops matching the code it was written for.

    A deferred import that no longer exists means the adapter went back to answering out
    of its own head - raising an error of its own, or bounding a read by a figure nobody
    chose - which is the defect each exemption was granted to close. One that is not on
    the list means the list was widened without the argument that widening it needs. Each
    exempt import is written once, so the count is compared as well as the set: a second
    site for a name already allowed is a second place to keep in step with the framework
    and passes the set comparison unnoticed.
    """

    found: list[tuple[str, str]] = []

    for module_path in _package_modules():
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        deferred = _deferred_import_nodes(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and id(node) in deferred:
                module = f"{'.' * node.level}{node.module or ''}"
                found.extend((module, alias.name) for alias in node.names)

    assert set(found) == ALLOWED_DEFERRED_IMPORTS
    assert len(found) == len(ALLOWED_DEFERRED_IMPORTS)


def test_importing_the_package_in_a_fresh_interpreter_pulls_in_no_web_framework() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", _LOAD_IN_ISOLATION, str(REPOSITORY_ROOT / "src")],
        capture_output=True,
        text=True,
        check=True,
    )
    loaded = json.loads(completed.stdout)

    assert loaded["frameworks"] == []
    assert set(loaded["framework_packages"]) == {"adapters", "contracts"}
