"""The contracts package must stay importable on its own.

Two guards, because either alone is easy to defeat. The static one reads every import
statement in the package and refuses anything that is not the standard library or the
package itself. The dynamic one loads the package in a fresh interpreter, under a name
that is not a child of ``bustan``, and asserts that nothing from ``bustan`` or from a
web framework ended up in ``sys.modules``.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

CONTRACTS_ROOT = Path(__file__).resolve().parents[3] / "src" / "bustan" / "contracts"

# Everything the package is allowed to import. Each name is a standard library module
# the contracts genuinely need; adding to this list means the package took on a new
# dependency, which is the thing this test exists to make visible.
ALLOWED_ROOTS = frozenset(
    {
        "__future__",
        "collections",
        "dataclasses",
        "json",
        "os",
        "typing",
        "urllib",
    }
)

_LOAD_IN_ISOLATION = """
import importlib.util
import json
import pathlib
import sys

package_root = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location(
    "isolated_contracts",
    package_root / "__init__.py",
    submodule_search_locations=[str(package_root)],
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

forbidden = {"bustan", "starlette", "anyio", "pydantic", "uvicorn"}
print(json.dumps(sorted(n for n in sys.modules if n.split(".")[0] in forbidden)))
"""


def _package_modules() -> list[Path]:
    return sorted(CONTRACTS_ROOT.glob("*.py"))


def test_the_package_has_modules_to_check() -> None:
    assert _package_modules(), f"no modules found under {CONTRACTS_ROOT}"


def test_no_module_imports_anything_but_the_standard_library_and_itself() -> None:
    offenders: list[str] = []

    for module_path in _package_modules():
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders.extend(
                    f"{module_path.name}: import {alias.name}"
                    for alias in node.names
                    if alias.name.split(".")[0] not in ALLOWED_ROOTS
                )
            elif isinstance(node, ast.ImportFrom):
                if node.level == 1:
                    continue
                if node.level > 1:
                    offenders.append(f"{module_path.name}: reaches outside the package")
                    continue
                root = (node.module or "").split(".")[0]
                if root not in ALLOWED_ROOTS:
                    offenders.append(f"{module_path.name}: from {node.module} import ...")

    assert offenders == []


def test_importing_the_package_in_a_fresh_interpreter_pulls_in_nothing_else() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", _LOAD_IN_ISOLATION, str(CONTRACTS_ROOT)],
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(completed.stdout) == []
