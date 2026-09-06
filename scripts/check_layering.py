"""Check that the package's import graph respects its declared layering.

The layer table below is the definition. A contributor adding a top-level package under
``src/bustan`` declares its layer here; the check fails with that instruction until they do,
so the table cannot be bypassed by forgetting it exists.
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "src" / "bustan"
PACKAGE_NAME = "bustan"
TABLE_LOCATION = "the layer table in scripts/check_layering.py"

# Modules directly under src/bustan are the package facade rather than a layer of their own.
ROOT_MODULES = "<root modules>"

# Text the scaffolder substitutes into a new project, not code this package runs. Three of the
# files hold a $package_name placeholder and are not parseable Python until it is substituted,
# which is why ruff, ty and coverage all exclude the same directory.
NON_SOURCE_DIRECTORIES = ("cli/templates",)

# Third-party web servers and web frameworks. A denylist rather than an allowlist of permitted
# dependencies: the rule being enforced is about web servers specifically, and an allowlist would
# reject every unrelated new dependency instead of the coupling this check exists to catch.
WEB_SERVER_PACKAGES = frozenset(
    {
        "aiohttp",
        "bottle",
        "cherrypy",
        "django",
        "falcon",
        "fastapi",
        "flask",
        "granian",
        "gunicorn",
        "hypercorn",
        "litestar",
        "pyramid",
        "quart",
        "sanic",
        "starlette",
        "tornado",
        "twisted",
        "uvicorn",
        "waitress",
        "werkzeug",
    }
)


@dataclass(frozen=True, slots=True)
class Layer:
    """One layer of the package: its name, its packages, and whether it may see a web server."""

    name: str
    packages: tuple[str, ...]
    may_import_web_server: bool = False


# Lowest layer first. A package may import its own layer and any layer below it, never above.
# Packages share a layer when they import each other, because a cycle has no lower half; where
# that is true of packages the architecture treats as distinct, it is recorded on the entry.
LAYERS: tuple[Layer, ...] = (
    # Protocols and neutral value types.
    Layer(name="contracts", packages=("contracts",)),
    # Injection, modules, lifecycle, and the decorators the kernel reads its metadata from.
    Layer(name="kernel", packages=("common", "kernel")),
    # Neutral request execution, the stages it runs and the observability it emits.
    # `pipeline` and `runtime` import each other at module scope, so neither can be ordered
    # below the other until that is untangled.
    Layer(name="runtime", packages=("observability", "pipeline", "runtime")),
    # The only layer permitted to import a web server.
    Layer(name="adapters", packages=("adapters",), may_import_web_server=True),
    # Everything assembled on top of the layers below.
    Layer(
        name="application",
        packages=(
            "addons",
            "app",
            "cli",
            "configuration",
            "openapi",
            "security",
            "testing",
            ROOT_MODULES,
        ),
    ),
)


def main(argv: Sequence[str] | None = None) -> int:
    """Check the layering of src/bustan, or print the layer table."""

    arguments = _parse_args(argv)
    if arguments.layers:
        for rank, layer in enumerate(LAYERS):
            server = " (may import a web server)" if layer.may_import_web_server else ""
            print(f"{rank}  {layer.name}{server}: {', '.join(layer.packages)}")
        return 0

    errors = check_layering(PACKAGE_ROOT)
    if errors:
        for error in errors:
            print(error)
        return 1

    print(f"Checked {len(LAYERS)} layers over src/{PACKAGE_NAME} with no layering violations.")
    return 0


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report layering violations and exit non-zero when any remain (the default).",
    )
    parser.add_argument(
        "--layers",
        action="store_true",
        help="Print the layer table, lowest layer first, and exit.",
    )
    return parser.parse_args(argv)


def check_layering(package_root: Path, layers: Sequence[Layer] = LAYERS) -> list[str]:
    """Return every layering violation under package_root, ordered by file and line."""

    errors = _check_table(package_root, layers)
    ranks = {package: rank for rank, layer in enumerate(layers) for package in layer.packages}

    for source_file in iter_source_files(package_root):
        package = owning_package(source_file, package_root)
        if package not in ranks:
            continue
        errors.extend(_check_file(source_file, package, package_root, layers, ranks))

    return errors


def _check_table(package_root: Path, layers: Sequence[Layer]) -> list[str]:
    """Return errors for packages the table does not declare, or declares and cannot find."""

    declared = {package for layer in layers for package in layer.packages}
    present = {
        directory.name
        for directory in package_root.iterdir()
        if directory.is_dir() and directory.name != "__pycache__"
    }

    errors = [
        f"{_relative(package_root / name)}: package {name!r} has no layer; declare it in "
        f"{TABLE_LOCATION}"
        for name in present - declared
    ]
    errors += [
        f"{TABLE_LOCATION}: declared package {name!r} is not present under "
        f"{_relative(package_root)}; the table is stale"
        for name in declared - present - {ROOT_MODULES}
    ]
    return errors


def _check_file(
    source_file: Path,
    package: str,
    package_root: Path,
    layers: Sequence[Layer],
    ranks: dict[str, int],
) -> list[str]:
    """Return the layering violations found in one source file."""

    layer = layers[ranks[package]]
    try:
        imports = collect_imports(source_file, package_root)
    except SyntaxError as error:
        return [f"{_relative(source_file)}:{error.lineno or 1}: cannot be parsed: {error.msg}"]

    errors: list[str] = []
    for line_number, module in imports:
        if module.split(".")[0] in WEB_SERVER_PACKAGES and not layer.may_import_web_server:
            errors.append(
                f"{_relative(source_file)}:{line_number}: {layer.name} may not import a web "
                f"server: {module}"
            )
            continue

        imported = imported_package(module, package_root)
        if imported is None or imported not in ranks or ranks[imported] <= ranks[package]:
            continue
        errors.append(
            f"{_relative(source_file)}:{line_number}: {layer.name} may not import "
            f"{layers[ranks[imported]].name}: {module}"
        )

    return errors


def iter_source_files(package_root: Path) -> list[Path]:
    """Return the Python files under package_root that this package actually runs."""

    excluded = tuple(package_root / directory for directory in NON_SOURCE_DIRECTORIES)
    return sorted(
        path
        for path in package_root.rglob("*.py")
        if not any(path.is_relative_to(directory) for directory in excluded)
    )


def collect_imports(source_file: Path, package_root: Path) -> list[tuple[int, str]]:
    """Return every module imported by source_file, as (line number, absolute module name).

    Function-local, ``try``-guarded and ``TYPE_CHECKING`` imports are all included. A deferred
    import is still a dependency of the file that writes it; it only moves the coupling to call
    time or to the type checker, and leaving it out would make the deferral a way around the rule.
    """

    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    imports: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append((node.lineno, _absolute_module(node, source_file, package_root)))

    # ast.walk yields breadth-first, so a deferred import inside a function comes back before the
    # module-level ones above it. Reporting has to read in the order the file is written.
    return sorted(imports)


def _absolute_module(node: ast.ImportFrom, source_file: Path, package_root: Path) -> str:
    """Resolve one ``from ... import`` target to an absolute module name."""

    if not node.level:
        return node.module or ""

    parts = (PACKAGE_NAME, *source_file.relative_to(package_root).parts[:-1])
    ascended = parts[: len(parts) - (node.level - 1)]
    return ".".join((*ascended, *(node.module.split(".") if node.module else ())))


def owning_package(source_file: Path, package_root: Path) -> str:
    """Return the top-level package a source file belongs to."""

    parts = source_file.relative_to(package_root).parts
    return parts[0] if len(parts) > 1 else ROOT_MODULES


def imported_package(module: str, package_root: Path) -> str | None:
    """Return the top-level package an imported module names, or None if it is not ours."""

    parts = module.split(".")
    if parts[0] != PACKAGE_NAME:
        return None
    if len(parts) > 1 and (package_root / parts[1]).is_dir():
        return parts[1]
    return ROOT_MODULES


def _relative(path: Path) -> str:
    """Return a repository-relative path when the path is inside the repository."""

    return str(path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path)


if __name__ == "__main__":
    raise SystemExit(main())
