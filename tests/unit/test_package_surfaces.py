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

# The two shapes that pull the reading of bound names in opposite directions. A name
# imported under the type-checking guard is never bound when the module runs, so a
# package declaring one advertises a name that raises at the import site. A name bound
# by a guarded import is bound, because one branch of the guard runs every time. A
# reader that follows every branch misses the first; one that follows none fails the
# second, which is correct code.
_TYPE_CHECKING_ONLY_BINDING = (
    "from typing import TYPE_CHECKING\n"
    "if TYPE_CHECKING:\n"
    "    from collections.abc import Iterator\n"
)
_RUNTIME_FALLBACK_BINDING = (
    "try:\n    from json import dumps\nexcept ImportError:\n    dumps = None\n"
)


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


def _guards_a_branch_that_never_runs(test: ast.expr) -> bool:
    """Report whether a conditional's test is false whenever the module is executed.

    ``TYPE_CHECKING`` is one such test however it is spelled, bare or through the
    module it is imported from. The attribute form is matched on the attribute name
    alone rather than on the module bound in front of it, because nothing read
    statically can tell the standard module from an alias of it, and a package that
    writes some other object's ``TYPE_CHECKING`` attribute into an import guard is not
    a shape worth reading a name out of either. A literal ``False`` is the same case
    written out. A negated or compound test is left alone: it reads as an ordinary
    conditional, which is where this reader already was.
    """

    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return isinstance(test, ast.Constant) and test.value is False


def _nested_statements(statement: ast.stmt) -> Iterator[ast.stmt]:
    """Yield the statements a conditional or a try block guards.

    The body of a conditional that cannot be true while the module runs is left out.
    Nothing in it is ever bound on the package, so following it would let a package
    declare a name only a type checker can see and still read as binding it. The
    ``else`` of such a conditional is the branch that does run, so it is still
    followed, and so is every branch of every other conditional.
    """

    fields = ("body", "orelse", "finalbody")
    if isinstance(statement, ast.If) and _guards_a_branch_that_never_runs(statement.test):
        fields = ("orelse",)
    for field in fields:
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
    whichever branch runs. The exception is a branch that never runs, such as the body
    of a type-checking guard, which binds nothing at all.
    """

    bound: set[str] = set()
    _collect(module.body, bound)
    return bound


def _star_imported_modules(module: ast.Module) -> list[str]:
    """Return the modules a package star imports from, spelled as they are written."""

    return [
        "." * statement.level + (statement.module or "")
        for statement in module.body
        if isinstance(statement, ast.ImportFrom)
        and any(alias.name == "*" for alias in statement.names)
    ]


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


def test_a_name_bound_only_under_the_type_checking_guard_reads_as_unbound() -> None:
    bound = _bound_names(ast.parse(_TYPE_CHECKING_ONLY_BINDING))

    assert "Iterator" not in bound, (
        "_bound_names counts a name imported under the type-checking guard as bound on "
        "its package. That guard is false whenever the module runs, so the name is never "
        "bound and `from package import *` raises AttributeError on it. A package "
        "declaring such a name is the failure the assertion below exists to catch, and "
        "this reading lets it through."
    )


def test_a_name_bound_by_a_runtime_fallback_reads_as_bound() -> None:
    bound = _bound_names(ast.parse(_RUNTIME_FALLBACK_BINDING))

    assert "dumps" in bound, (
        "_bound_names counts a name bound by a guarded import as unbound on its package. "
        "One branch of such a fallback runs every time the module is executed, so the "
        "name is bound, and reporting it makes the assertion below fail correct code. "
        "Skip the branch that never runs, not every branch."
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


def test_no_package_hides_what_it_binds_behind_a_star_import() -> None:
    hidden = sorted(
        f"{name} (from {source} import *)"
        for name, module in _checked_packages()
        for source in _star_imported_modules(module)
    )

    assert not hidden, (
        f"A wildcard import stands between a package and the names it binds: "
        f"{', '.join(hidden)}. Nothing read statically can see through one, so a name "
        "arriving that way reads as unbound and the assertion above reports correct "
        "code as broken. It is also the accident an explicit __all__ exists to prevent. "
        "Import what the package re-exports by name."
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
