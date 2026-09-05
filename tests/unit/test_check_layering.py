"""Unit tests for the package layering check."""

from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType


def test_check_layering_accepts_a_tree_that_respects_the_layers(tmp_path: Path) -> None:
    checker = _load_checker_module()
    package_root = _build_package(
        tmp_path,
        {
            "contracts/request.py": "class HttpRequest: ...\n",
            "core/container.py": "from bustan.contracts.request import HttpRequest\n",
            "adapters/starlette/adapter.py": "from starlette.responses import Response\n",
        },
    )

    errors = checker.check_layering(package_root, _layers(checker))

    assert errors == []


def test_check_layering_reports_an_import_from_a_higher_layer(tmp_path: Path) -> None:
    checker = _load_checker_module()
    package_root = _build_package(
        tmp_path,
        {
            "contracts/request.py": "from bustan.core.container import Container\n",
            "core/container.py": "class Container: ...\n",
            "adapters/starlette/adapter.py": "import starlette\n",
        },
    )

    errors = checker.check_layering(package_root, _layers(checker))

    assert len(errors) == 1
    assert errors[0].endswith(
        "contracts/request.py:1: contracts may not import kernel: bustan.core.container"
    )


def test_check_layering_reports_a_web_server_outside_the_adapters(tmp_path: Path) -> None:
    checker = _load_checker_module()
    package_root = _build_package(
        tmp_path,
        {
            "contracts/request.py": "class HttpRequest: ...\n",
            "core/container.py": (
                "def build() -> object:\n    from starlette.responses import Response\n\n"
                "    return Response\n"
            ),
            "adapters/starlette/adapter.py": "import starlette\n",
        },
    )

    errors = checker.check_layering(package_root, _layers(checker))

    assert len(errors) == 1
    assert errors[0].endswith(
        "core/container.py:2: kernel may not import a web server: starlette.responses"
    )


def test_check_layering_reports_a_package_with_no_declared_layer(tmp_path: Path) -> None:
    checker = _load_checker_module()
    package_root = _build_package(
        tmp_path,
        {
            "contracts/request.py": "class HttpRequest: ...\n",
            "core/container.py": "class Container: ...\n",
            "adapters/starlette/adapter.py": "import starlette\n",
            "health/endpoint.py": "class HealthEndpoint: ...\n",
        },
    )

    errors = checker.check_layering(package_root, _layers(checker))

    assert len(errors) == 1
    assert "package 'health' has no layer" in errors[0]
    assert "scripts/check_layering.py" in errors[0]


def test_check_layering_reports_a_table_entry_with_no_package(tmp_path: Path) -> None:
    checker = _load_checker_module()
    package_root = _build_package(tmp_path, {"contracts/request.py": "class HttpRequest: ...\n"})

    errors = checker.check_layering(package_root, _layers(checker))

    assert {error.split(": ", maxsplit=1)[1] for error in errors} == {
        f"declared package {name!r} is not present under {package_root}; the table is stale"
        for name in ("core", "adapters")
    }


def test_collect_imports_resolves_relative_imports(tmp_path: Path) -> None:
    checker = _load_checker_module()
    package_root = _build_package(
        tmp_path,
        {
            "core/module/graph.py": (
                "from ...contracts.request import HttpRequest\nimport starlette\n"
            )
        },
    )

    imports = checker.collect_imports(package_root / "core" / "module" / "graph.py", package_root)

    assert imports == [(1, "bustan.contracts.request"), (2, "starlette")]


def test_iter_source_files_skips_the_scaffolder_templates(tmp_path: Path) -> None:
    checker = _load_checker_module()
    package_root = _build_package(
        tmp_path,
        {
            "cli/main.py": "def main() -> int:\n    return 0\n",
            "cli/templates/app/app_module.py": "from bustan import Module\n",
        },
    )

    assert checker.iter_source_files(package_root) == [package_root / "cli" / "main.py"]


def _layers(checker: ModuleType) -> tuple[object, ...]:
    """Return a three-layer table small enough to build a tree for."""

    return (
        checker.Layer(name="contracts", packages=("contracts",)),
        checker.Layer(name="kernel", packages=("core",)),
        checker.Layer(name="adapters", packages=("adapters",), may_import_web_server=True),
    )


def _build_package(tmp_path: Path, sources: dict[str, str]) -> Path:
    """Write a throwaway `bustan` package from relative paths to file contents."""

    package_root = tmp_path / "bustan"
    for relative_path, source in sources.items():
        path = package_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return package_root


def _load_checker_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "check_layering.py"
    module_spec = spec_from_file_location("check_layering", script_path)
    assert module_spec is not None
    assert module_spec.loader is not None

    module = module_from_spec(module_spec)
    # Registered before execution because the script's frozen dataclass resolves its postponed
    # annotations through sys.modules, and a module absent from it cannot be resolved against.
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module
