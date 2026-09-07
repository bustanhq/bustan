"""Unit tests holding the package surface criterion for the whole source tree.

Every package under ``src/bustan`` declares an explicit ``__all__``, and every name a
declaration carries is bound by the package carrying it. Both facts are true of the
tree and neither is otherwise checked, so both decay without anyone seeing it. A
package added without a declaration goes back to exporting whatever its imports happen
to leave behind, which is an accident of import order rather than a decision. A symbol
renamed without its declaration leaves the old name advertised, and ``from package
import *`` then raises ``AttributeError`` at the import site rather than anywhere a
reader would think to look.

The declarations are read out of each ``__init__.py`` with ``ast`` instead of by
importing the packages, because two packages in this tree cannot be imported in a bare
development environment: the Starlette adapter needs an optional extra that a plain
install does not bring in, and the scaffolder's template package ships modules holding
placeholders that are not valid Python until the scaffolder substitutes them. Reading
the files keeps these assertions independent of both, and of whether ``bustan`` is
installed at all.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "bustan"

# A package may be left out of both assertions only by naming it here with the reason
# it cannot meet them, so that an omission is a decision on the record rather than a
# silent gap. It is empty because every package in the tree declares an explicit
# ``__all__`` and binds every name in it.
UNCHECKED_PACKAGES: dict[str, str] = {}

# The two forms a declaration takes in this tree. An annotated one parses to an
# ``ast.AnnAssign`` and a bare one to an ``ast.Assign``, and a reader that knows only
# the second sees no declaration at all in more than half the packages here.
_PLAIN_DECLARATION = "__all__ = ('Alpha', 'Beta')\n"
_ANNOTATED_DECLARATION = "__all__: tuple[str, ...] = ('Alpha', 'Beta')\n"


def _parse(init_path: Path) -> ast.Module:
    """Parse a package's ``__init__.py`` without importing anything it names."""

    return ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))


def _dotted_name(init_path: Path) -> str:
    """Return the import path of the package whose ``__init__.py`` this is."""

    return ".".join(init_path.parent.relative_to(PACKAGE_ROOT.parent).parts)


def _all_packages() -> list[tuple[str, ast.Module]]:
    """Return every package in the tree, by import path, with its parsed source."""

    return sorted(
        ((_dotted_name(path), _parse(path)) for path in PACKAGE_ROOT.rglob("__init__.py")),
        key=lambda package: package[0],
    )


def _checked_packages() -> list[tuple[str, ast.Module]]:
    """Return the packages these assertions apply to, minus the recorded exclusions."""

    return [package for package in _all_packages() if package[0] not in UNCHECKED_PACKAGES]


def _declared_all(module: ast.Module) -> tuple[str, ...] | None:
    """Return the names a module declares in ``__all__``, or ``None`` if it declares none.

    ``None`` also covers a declaration built at runtime rather than written out, which
    is not explicit: nothing can read it without executing the module.
    """

    for statement in module.body:
        if isinstance(statement, ast.Assign):
            targets: list[ast.expr] = list(statement.targets)
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
        else:
            continue

        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets):
            continue
        if statement.value is None:
            return None
        try:
            declared = ast.literal_eval(statement.value)
        except ValueError:
            return None
        if not isinstance(declared, tuple | list) or not all(
            isinstance(name, str) for name in declared
        ):
            return None
        return tuple(declared)

    return None


def _nested_statements(statement: ast.stmt) -> Iterator[ast.stmt]:
    """Yield the statements a conditional or a try block guards."""

    for field in ("body", "orelse", "finalbody"):
        yield from getattr(statement, field, ())
    for handler in getattr(statement, "handlers", ()):
        yield from handler.body


def _collect_target(target: ast.expr, bound: set[str]) -> None:
    """Record the names an assignment target binds, unpacking tuples and lists."""

    if isinstance(target, ast.Name):
        bound.add(target.id)
    elif isinstance(target, ast.Tuple | ast.List):
        for element in target.elts:
            _collect_target(element, bound)
    elif isinstance(target, ast.Starred):
        _collect_target(target.value, bound)


def _collect(statements: Iterable[ast.stmt], bound: set[str]) -> None:
    """Record every name the given module-level statements bind."""

    for statement in statements:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                # ``import a.b`` binds ``a``, not ``a.b``, unless it is given a name.
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(statement, ast.ImportFrom):
            for alias in statement.names:
                if alias.name != "*":
                    bound.add(alias.asname or alias.name)
        elif isinstance(statement, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            bound.add(statement.name)
        elif isinstance(statement, ast.Assign):
            for target in statement.targets:
                _collect_target(target, bound)
        elif isinstance(statement, ast.AnnAssign):
            _collect_target(statement.target, bound)
        else:
            _collect(_nested_statements(statement), bound)


def _bound_names(module: ast.Module) -> set[str]:
    """Return the names a package binds on itself.

    Bodies of functions and classes are not followed, because a name bound inside one
    is bound on that scope and not on the package. Bodies of conditionals and try
    blocks are followed, because a guarded import binds its name on the package for
    whichever branch runs.
    """

    bound: set[str] = set()
    _collect(module.body, bound)
    return bound


def test_the_scan_reaches_the_whole_package_tree() -> None:
    discovered = [name for name, _ in _all_packages()]

    assert "bustan" in discovered and len(discovered) > 1, (
        f"The scan of {PACKAGE_ROOT} found {discovered or 'no packages'}, so the assertions "
        "below hold vacuously over an empty tree rather than over the source. Point "
        "PACKAGE_ROOT at the package tree."
    )


def test_both_declaration_forms_are_read() -> None:
    forms = {
        "bare assignment": _declared_all(ast.parse(_PLAIN_DECLARATION)),
        "annotated assignment": _declared_all(ast.parse(_ANNOTATED_DECLARATION)),
    }
    unread = sorted(form for form, declared in forms.items() if declared != ("Alpha", "Beta"))

    assert not unread, (
        f"_declared_all reads no names from these declaration forms: {', '.join(unread)}. A "
        "package that writes its __all__ that way reads as declaring nothing, and the "
        "assertions below are blind to it."
    )


def test_every_package_declares_an_explicit_all() -> None:
    undeclared = sorted(
        name for name, module in _checked_packages() if _declared_all(module) is None
    )

    assert not undeclared, (
        f"No explicit __all__ in the __init__.py of {', '.join(undeclared)}. What such a "
        "package exports is an accident of the order its imports happen to run in. Declare "
        "the exported names as a literal tuple, or list the package in UNCHECKED_PACKAGES "
        "with the reason it cannot carry one."
    )


def test_every_declared_name_is_bound_by_its_package() -> None:
    unbound: list[str] = []
    for name, module in _checked_packages():
        declared = _declared_all(module)
        if declared is None:
            continue
        missing = sorted(set(declared) - _bound_names(module))
        if missing:
            unbound.append(f"{name} ({', '.join(missing)})")

    assert not unbound, (
        f"__all__ advertises a name its package does not bind: {'; '.join(unbound)}. "
        "`from <package> import *` raises AttributeError on such a name, at the import "
        "site rather than anywhere the reader would look. Drop the stale entry or "
        "restore the binding. A wildcard import in the package's own __init__.py reads "
        "as binding nothing here, because nothing read statically can see through one."
    )


def test_no_exclusion_names_a_package_that_is_not_in_the_tree() -> None:
    known = {name for name, _ in _all_packages()}
    absent = sorted(name for name in UNCHECKED_PACKAGES if name not in known)

    assert not absent, (
        f"UNCHECKED_PACKAGES excuses {', '.join(absent)}, which is not a package under "
        f"{PACKAGE_ROOT}, so the exclusion covers nothing and is stale."
    )


def test_every_exclusion_states_a_reason() -> None:
    unexplained = sorted(name for name, reason in UNCHECKED_PACKAGES.items() if not reason.strip())

    assert not unexplained, (
        f"UNCHECKED_PACKAGES lists {', '.join(unexplained)} with no reason. An omission "
        "without one is indistinguishable from an oversight."
    )
