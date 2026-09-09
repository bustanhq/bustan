"""The stability guide and the package's export set must not be able to disagree.

The guide is the authority and the export set derives from it, which is a claim worth
nothing unless something checks it. Nothing did: the guide could call a symbol
supported that no module exported, and could list a set of internal namespaces the
package had outgrown, and both stayed true-looking because the only reader was a
person. These tests are the comparison, so a promotion that stops halfway and a
namespace that appears without being classified both fail here.
"""

from __future__ import annotations

import re
from importlib import import_module
from importlib.util import module_from_spec, spec_from_file_location
from inspect import Parameter, signature
from pathlib import Path
from types import ModuleType

import bustan

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = REPOSITORY_ROOT / "src" / "bustan"
STABILITY_GUIDE = REPOSITORY_ROOT / "docs" / "reference" / "stability.md"
GENERATOR_PATH = REPOSITORY_ROOT / "scripts" / "generate_api_reference.py"

SUPPORTED_MODULES = ("bustan", "bustan.errors", "bustan.testing")

_BULLETED_MODULE = re.compile(r"- `([A-Za-z0-9_.*]+)`")
_BACKTICKED = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")
_CREATE_APP_KEYWORD = re.compile(r"`create_app\(([a-z_]+)=")


def _guide_lines() -> list[str]:
    return STABILITY_GUIDE.read_text(encoding="utf-8").splitlines()


def _section(heading: str) -> list[str]:
    """Return the lines under one heading, up to the next heading of any level."""

    collected: list[str] = []
    in_section = False
    for line in _guide_lines():
        if line.startswith("#"):
            if in_section:
                break
            in_section = line.strip() == heading
            continue
        if in_section:
            collected.append(line)
    assert collected, f"the stability guide has no {heading!r} section"
    return collected


def _bulleted_modules(heading: str) -> frozenset[str]:
    """Collect the module names the guide bullets under one heading."""

    return frozenset(
        match.group(1).removesuffix(".*")
        for line in _section(heading)
        if (match := _BULLETED_MODULE.fullmatch(line.strip())) is not None
    )


def _extension_point_rows() -> tuple[tuple[str, str, str], ...]:
    """Return the extension point table as (name, symbols, installation) cells."""

    rows: list[tuple[str, str, str]] = []
    for line in _section("## Supported Extension Points"):
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) != 3 or set(cells[0]) <= {"-", " "} or cells[0] == "Extension point":
            continue
        rows.append((cells[0], cells[1], cells[2]))
    assert rows, "no extension point rows parsed out of the stability guide"
    return tuple(rows)


def _package_namespaces() -> frozenset[str]:
    """Return every top-level namespace of the package a caller could import."""

    directories = {path.name for path in PACKAGE_ROOT.iterdir() if (path / "__init__.py").exists()}
    modules = {
        path.stem
        for path in PACKAGE_ROOT.glob("*.py")
        if not path.stem.startswith("_") and path.stem != "__init__"
    }
    return frozenset(directories | modules)


def _load_reference_generator() -> ModuleType:
    """Import the API reference generator by path, as the generator's own tests do."""

    spec = spec_from_file_location("generate_api_reference", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    generator = module_from_spec(spec)
    spec.loader.exec_module(generator)
    return generator


def test_every_symbol_the_guide_calls_supported_is_exported() -> None:
    exported = frozenset(bustan.__all__)
    unexported = sorted(
        f"{name}: {symbol}"
        for name, symbols, _installation in _extension_point_rows()
        for symbol in _BACKTICKED.findall(symbols)
        if symbol not in exported
    )

    assert unexported == [], (
        "the stability guide names these as supported but bustan does not export them: "
        + "; ".join(unexported)
    )


def test_every_create_app_keyword_the_guide_names_is_a_real_keyword() -> None:
    accepted = {
        name
        for name, parameter in signature(bustan.create_app).parameters.items()
        if parameter.kind is Parameter.KEYWORD_ONLY
    }
    named = {
        keyword
        for _name, _symbols, installation in _extension_point_rows()
        for keyword in _CREATE_APP_KEYWORD.findall(installation)
    }

    assert named, "no create_app keyword parsed out of the stability guide"
    assert sorted(named - accepted) == []


def test_the_internal_namespace_list_matches_the_package_tree() -> None:
    supported = _bulleted_modules("## Supported Public Surface")
    internal = _bulleted_modules("## Internal Modules")

    assert supported == set(SUPPORTED_MODULES)
    assert {name.removeprefix("bustan.") for name in internal} == _package_namespaces() - {
        "errors",
        "testing",
    }


def test_every_supported_symbol_is_defined_under_a_classified_namespace() -> None:
    classified = {
        name.removeprefix("bustan.")
        for name in _bulleted_modules("## Internal Modules")
        | _bulleted_modules("## Supported Public Surface")
    }

    unclassified: list[str] = []
    for module_name in SUPPORTED_MODULES:
        module = import_module(module_name)
        for export_name in module.__all__:
            origin = getattr(getattr(module, export_name), "__module__", None)
            if not isinstance(origin, str) or not origin.startswith("bustan."):
                continue
            if origin.split(".")[1] not in classified:
                unclassified.append(f"{module_name}.{export_name} is defined in {origin}")

    assert sorted(unclassified) == [], (
        "the stability guide classifies no namespace for: " + "; ".join(sorted(unclassified))
    )


def test_the_guide_and_the_reference_generator_name_the_same_stable_modules() -> None:
    generator = _load_reference_generator()

    assert tuple(sorted(generator.STABLE_MODULES)) == tuple(sorted(SUPPORTED_MODULES))
    assert _bulleted_modules("## Supported Public Surface") == set(generator.STABLE_MODULES)
