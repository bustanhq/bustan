"""Unit tests holding every package in the tree to an explicit, honest ``__all__``.

A package that declares no ``__all__`` has a public surface that is an accident of which
names its imports happen to leave behind, so a reader cannot tell what the package meant
to offer from what it merely failed to hide. An ``__all__`` that names something the
package does not bind is the same defect from the other side: it advertises a name that
raises ``AttributeError`` at the import site rather than anywhere a reader would think to
look. Both are invisible to whoever caused them, so they are asserted here.

The declarations are read with ``ast`` rather than by importing the tree. Two packages
cannot be imported in a bare development environment: the Starlette adapter is the only
place that imports Starlette, which is an optional extra, and the scaffolder's
application templates carry placeholders that are not valid Python until the scaffolder
substitutes them. Reading the source keeps this file independent of both, and of whether
the package is installed at all.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "bustan"

# A package may be left out of the assertions below only by naming it here with the
# reason, so that an omission is a decision on the record rather than a silent gap. It is
# empty because every package in the tree declares an ``__all__`` and binds every name it
# declares.
UNSURFACED_PACKAGES: dict[str, str] = {}


@dataclass(frozen=True, slots=True)
class _PackageSurface:
    """What one package's ``__init__.py`` declares and what it binds.

    ``declared`` is ``None`` when the module declares no ``__all__`` at all, which is
    distinct from declaring an empty one: a package that exports nothing on purpose says
    so, and this test can tell the two apart.
    """

    name: str
    declared: tuple[str, ...] | None
    bound: frozenset[str]
    star_imports: tuple[str, ...]


def _declared_all(body: list[ast.stmt]) -> tuple[str, ...] | None:
    """Return the ``__all__`` a module body declares, or ``None`` when it declares none.

    The declaration may be annotated, and most of them in this tree are. A bare
    annotation with no value binds nothing at import time, so it is not a declaration.
    """

    for node in body:
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue

        names_all = any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in targets
        )
        if not names_all or node.value is None:
            continue

        return tuple(ast.literal_eval(node.value))

    return None


def _target_names(target: ast.expr) -> Iterator[str]:
    """Yield the names one assignment target binds, unpacking tuples and lists."""

    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, ast.Starred):
        yield from _target_names(target.value)
    elif isinstance(target, ast.Tuple | ast.List):
        for element in target.elts:
            yield from _target_names(element)


def _bound_names(body: list[ast.stmt]) -> frozenset[str]:
    """Return the names a module body binds unconditionally at import time.

    Only top level statements count. A name bound inside a conditional block, a type
    checking guard most of all, is not bound when the module actually runs, and counting
    it would let a package advertise a name that ``from package import *`` cannot
    produce. A package that binds part of its surface conditionally therefore reports as
    failing here, which is the loud direction to be wrong in.
    """

    names: set[str] = set()
    for node in body:
        if isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names if alias.name != "*")
        elif isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names.update(_target_names(target))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            names.update(_target_names(node.target))

    return frozenset(names)


def _star_imports(body: list[ast.stmt]) -> tuple[str, ...]:
    """Return the modules a body star imports from, spelled as they are written."""

    return tuple(
        "." * node.level + (node.module or "")
        for node in body
        if isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names)
    )


def _read_surfaces() -> tuple[_PackageSurface, ...]:
    """Read every package under the tree from its source, importing none of it."""

    surfaces: list[_PackageSurface] = []
    for path in sorted(PACKAGE_ROOT.rglob("__init__.py")):
        name = ".".join(path.relative_to(PACKAGE_ROOT.parent).parent.parts)
        body = ast.parse(path.read_text(encoding="utf-8")).body

        try:
            declared = _declared_all(body)
        except ValueError as error:
            raise AssertionError(
                f"{name} declares an __all__ that cannot be read without importing the "
                f"package: {error}. Keep the declaration a literal tuple of strings, so "
                "that what the package exports can be read where it is written."
            ) from error

        surfaces.append(
            _PackageSurface(
                name=name,
                declared=declared,
                bound=_bound_names(body),
                star_imports=_star_imports(body),
            )
        )

    return tuple(surfaces)


def test_the_package_walk_finds_the_tree() -> None:
    names = {surface.name for surface in _read_surfaces()}

    assert "bustan" in names and len(names) > 1, (
        f"Walking {PACKAGE_ROOT} for packages found {sorted(names)}. Every other "
        "assertion in this file derives what it expects from that walk, so a walk that "
        "finds nothing passes all of them while checking nothing."
    )


def test_every_package_declares_an_explicit_all() -> None:
    missing = sorted(
        surface.name
        for surface in _read_surfaces()
        if surface.declared is None and surface.name not in UNSURFACED_PACKAGES
    )

    assert not missing, (
        f"No explicit __all__ in the __init__.py of: {', '.join(missing)}. Declare one, "
        "as an empty tuple where the package exports nothing, so that the package's "
        "public surface is a decision rather than an accident of import order, or name "
        "the package in UNSURFACED_PACKAGES with the reason it cannot have one."
    )


def test_every_name_in_all_is_bound_on_its_package() -> None:
    unbound = sorted(
        f"{surface.name}.{name}"
        for surface in _read_surfaces()
        if surface.name not in UNSURFACED_PACKAGES
        for name in surface.declared or ()
        if name not in surface.bound
    )

    assert not unbound, (
        f"__all__ advertises {', '.join(unbound)}, which the package's __init__.py does "
        "not bind at import time, so `from package import *` raises AttributeError at "
        "the import site. Correct the entry to the name the package binds, or drop it."
    )


def test_no_package_hides_what_it_binds_behind_a_star_import() -> None:
    hidden = sorted(
        f"{surface.name} (from {source} import *)"
        for surface in _read_surfaces()
        for source in surface.star_imports
    )

    assert not hidden, (
        f"{', '.join(hidden)}. A star import binds names this file cannot read from the "
        "source, so the assertion that every declared name is bound would report those "
        "names as missing. Import what the package re-exports by name."
    )


def test_no_exclusion_names_a_package_outside_the_tree() -> None:
    names = {surface.name for surface in _read_surfaces()}
    unknown = sorted(name for name in UNSURFACED_PACKAGES if name not in names)

    assert not unknown, (
        f"UNSURFACED_PACKAGES excuses {', '.join(unknown)}, which is not a package in "
        "the tree, so the exclusion covers nothing and is stale. Remove the entry."
    )


def test_every_exclusion_states_a_reason() -> None:
    unexplained = sorted(name for name, reason in UNSURFACED_PACKAGES.items() if not reason.strip())

    assert not unexplained, (
        f"UNSURFACED_PACKAGES lists {', '.join(unexplained)} with no reason. An omission "
        "without one is indistinguishable from an oversight."
    )
