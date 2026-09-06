"""Every directory of framework source is a regular package with a declared surface.

A directory without ``__init__.py`` still imports, as an implicit namespace package,
which is why the gap survived so long. It is not free: namespace packages resolve
across every entry on the path, so a directory of the same name anywhere else can
contribute modules to it, and tooling that walks the package sees a different tree
from the one the interpreter assembles.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[3] / "src" / "bustan"

# Packages that deliberately export nothing from their top level: callers import the
# module they want by name. They still declare it, so "exports nothing" is a decision
# on the page rather than an omission a reader has to infer.
PACKAGES_WITHOUT_A_TOP_LEVEL_SURFACE = (
    "common",
    "kernel/lifecycle",
    "cli/services",
    "cli/commands",
    "cli/templates",
    "cli/templates/app",
    "adapters",
)


def _directories_holding_python_files() -> list[Path]:
    return sorted(
        {
            module_path.parent
            for module_path in PACKAGE_ROOT.rglob("*.py")
            if "__pycache__" not in module_path.parts
        }
    )


def _declared_all(init_path: Path) -> tuple[str, ...] | None:
    """Return the ``__all__`` a package declares literally, or ``None`` when it has none."""

    tree = ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            targets: list[ast.expr] = [node.target]
            value = node.value
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        else:
            continue

        names_assigned = {target.id for target in targets if isinstance(target, ast.Name)}
        if "__all__" in names_assigned and value is not None:
            return tuple(ast.literal_eval(value))
    return None


def test_no_directory_of_source_resolves_as_a_namespace_package() -> None:
    missing = [
        str(directory.relative_to(PACKAGE_ROOT))
        for directory in _directories_holding_python_files()
        if not (directory / "__init__.py").exists()
    ]

    assert missing == []


def test_packages_with_no_top_level_surface_still_declare_one() -> None:
    for relative_path in PACKAGES_WITHOUT_A_TOP_LEVEL_SURFACE:
        init_path = PACKAGE_ROOT / relative_path / "__init__.py"

        assert init_path.exists(), relative_path
        assert _declared_all(init_path) == (), relative_path


def test_the_contracts_package_declares_the_names_it_defines() -> None:
    assert _declared_all(PACKAGE_ROOT / "contracts" / "__init__.py") == (
        "AbstractHttpAdapter",
        "AdapterCapabilities",
        "AdapterRoute",
        "Headers",
        "HttpClientInfo",
        "HttpFileResponse",
        "HttpFormData",
        "HttpQueryParams",
        "HttpRequest",
        "HttpRequestState",
        "HttpResponse",
        "HttpResponseValue",
        "HttpStreamResponse",
        "HttpUrl",
        "NativeHttpRequest",
        "NativeHttpResponse",
        "QueryParams",
        "RateLimitDecision",
        "RequestSlots",
        "RequestState",
        "RouteHandler",
        "Url",
        "as_http_request",
        "names_native_request",
        "request_slots",
    )
