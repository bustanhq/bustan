"""Only the adapter packages may know a web server exists.

The framework claims to be server agnostic; that claim is only worth something if
something objects when a module outside ``bustan.adapters`` reaches for a transport.
This walks every import statement in the package rather than grepping for a name, so
a mention in a comment or a docstring is not mistaken for a dependency.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[3] / "src" / "bustan"
ADAPTER_ROOT = PACKAGE_ROOT / "adapters"
TRANSPORT_ROOTS = frozenset({"starlette", "uvicorn"})

# The scaffolder writes an application for a user to run, so its templates import the
# test client that application is served by. They are shipped as data, never imported.
TEMPLATE_ROOT = PACKAGE_ROOT / "cli" / "templates"

# Modules that still import a transport and are owned by another ticket. Each entry is
# a debt this test makes visible rather than lets pass silently.
KNOWN_TRANSPORT_IMPORTERS = frozenset(
    {
        "app/application.py",
        "runtime/compiler.py",
        "runtime/conformance.py",
        "testing/builder.py",
    }
)


def _transport_importers() -> set[str]:
    offenders: set[str] = set()
    for module_path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if "__pycache__" in module_path.parts:
            continue
        if ADAPTER_ROOT in module_path.parents or TEMPLATE_ROOT in module_path.parents:
            continue
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                roots = {(node.module or "").split(".")[0]} if node.level == 0 else set()
            else:
                continue
            if roots & TRANSPORT_ROOTS:
                offenders.add(str(module_path.relative_to(PACKAGE_ROOT)))
    return offenders


def test_no_module_this_ticket_owns_still_imports_a_transport() -> None:
    assert _transport_importers() <= KNOWN_TRANSPORT_IMPORTERS


def test_every_module_on_the_request_path_is_free_of_a_transport() -> None:
    request_path = {
        "runtime/adapter.py",
        "runtime/execution.py",
        "runtime/responses.py",
        "runtime/routing.py",
        "pipeline/middleware.py",
        "pipeline/filters.py",
        "security/throttler.py",
    }

    assert _transport_importers() & request_path == set()


def test_the_contracts_package_never_reaches_for_a_transport() -> None:
    assert not any(name.startswith("contracts/") for name in _transport_importers())


def test_the_injection_kernel_never_reaches_for_a_transport() -> None:
    """The container decides what a request means, so it may not know what serves one."""

    assert not any(name.startswith("kernel/") for name in _transport_importers())


def test_the_known_debt_list_names_only_modules_that_still_exist() -> None:
    missing = [name for name in KNOWN_TRANSPORT_IMPORTERS if not (PACKAGE_ROOT / name).exists()]

    assert missing == []
