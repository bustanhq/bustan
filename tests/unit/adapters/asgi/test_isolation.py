"""The ASGI adapter must stay free of every web framework.

Two guards, because either alone is easy to defeat. The static one reads every import
statement in the package and refuses anything that is neither the standard library, the
package itself, nor the shared contracts. The dynamic one loads the package in a fresh
interpreter, with the ``bustan`` package replaced by an empty stand-in so that importing
the framework cannot be what satisfies an import, and asserts that no web framework and
no framework module other than the contracts ended up in ``sys.modules``.
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
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                offenders.extend(_offending_import(module_path, node))

    assert offenders == []


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
