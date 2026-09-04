"""Unit tests for constructor annotation planning.

The interesting cases turn on which namespace an annotation is evaluated in, so those
are exercised against packages this module writes to disk and imports. A fixture file
would be read in whatever namespace the fixture happened to be imported from, which is
the very thing under test.
"""

from __future__ import annotations

import importlib
import sys
import textwrap
from typing import TYPE_CHECKING, Annotated, Optional

import pytest

from bustan.common.decorators.injectable import Inject, OptionalDep
from bustan.core.errors import ProviderResolutionError
from bustan.core.ioc.planning.annotations import (
    _ConstructorNamespace,
    plan_constructor_dependencies,
)
from bustan.core.ioc.tokens import REQUEST, InjectionToken

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from types import ModuleType
    from typing import Protocol

    class ModuleBuilder(Protocol):
        """Writes a throwaway package and returns its imported modules by name."""

        def __call__(self, **sources: str) -> dict[str, ModuleType]: ...


class Dep:
    pass


class Other:
    pass


class NotProvided:
    pass


DEFAULT_DEP = Dep()
SENTINEL = NotProvided()
UNHASHABLE_TOKEN: list[str] = ["unhashable"]


class UsesDep:
    def __init__(self, dep: Dep) -> None:
        self.dep = dep


class UsesKeywordOnlyDep:
    def __init__(self, *, dep: Dep) -> None:
        self.dep = dep


class UsesOptional:
    def __init__(self, dep: Optional[Dep]) -> None:  # noqa: UP045
        self.dep = dep


class UsesPipeNone:
    def __init__(self, dep: Dep | None) -> None:
        self.dep = dep


class UsesPipeNoneWithOptionalDep:
    def __init__(self, dep: Annotated[Dep | None, OptionalDep()]) -> None:
        self.dep = dep


class UsesPlainWithOptionalDep:
    def __init__(self, dep: Annotated[Dep, OptionalDep()]) -> None:
        self.dep = dep


class UsesAnnotatedNote:
    def __init__(self, dep: Annotated[Dep, "unrelated metadata"]) -> None:
        self.dep = dep


class UsesUnionWithoutNone:
    def __init__(self, dep: Dep | Other) -> None:
        self.dep = dep


class UsesUnionOfManyWithNone:
    def __init__(self, dep: Dep | Other | None) -> None:
        self.dep = dep


class DefaultedScalar:
    def __init__(self, retries: int = 3) -> None:
        self.retries = retries


class DefaultedUnannotated:
    def __init__(self, retries=3) -> None:
        self.retries = retries


class DefaultedUnionNone:
    def __init__(self, dep: NotProvided | None = None) -> None:
        self.dep = dep


class DefaultedOptionalDep:
    def __init__(self, dep: Annotated[NotProvided, OptionalDep()] = SENTINEL) -> None:
        self.dep = dep


class DefaultedVisibleDep:
    def __init__(self, dep: Dep = DEFAULT_DEP) -> None:
        self.dep = dep


class DefaultedUnhashableToken:
    def __init__(self, value: Annotated[str, Inject(UNHASHABLE_TOKEN)] = "fallback") -> None:
        self.value = value


class DefaultedContainerToken:
    def __init__(self, request: Annotated[object, Inject(REQUEST)] = None) -> None:
        self.request = request


class DuplicateInject:
    def __init__(self, value: Annotated[str, Inject("A"), Inject("B")]) -> None:
        self.value = value


class Unannotated:
    def __init__(self, dep) -> None:
        self.dep = dep


class Variadic:
    def __init__(self, *args: Dep) -> None:
        self.args = args


class VariadicKeywords:
    def __init__(self, **kwargs: Dep) -> None:
        self.kwargs = kwargs


class Bare:
    pass


class NewOnly:
    dep: Dep

    def __new__(cls, dep: Dep) -> NewOnly:
        instance = super().__new__(cls)
        instance.dep = dep
        return instance


class HeaderMap(dict[str, str]):
    pass


class CustomError(Exception):
    pass


@pytest.fixture
def build_modules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleBuilder]:
    """Return a builder that writes a package of modules and imports them."""

    package_name = f"generated_{tmp_path.name}".replace("-", "_")

    def build(**sources: str) -> dict[str, ModuleType]:
        package = tmp_path / package_name
        package.mkdir()
        (package / "__init__.py").write_text("")
        for name, source in sources.items():
            (package / f"{name}.py").write_text(textwrap.dedent(source))
        monkeypatch.syspath_prepend(str(tmp_path))
        importlib.invalidate_caches()
        return {name: importlib.import_module(f"{package_name}.{name}") for name in sources}

    yield build

    for name in [name for name in sys.modules if name.split(".")[0] == package_name]:
        del sys.modules[name]


def test_lexical_scope_wins_over_a_visible_token_of_the_same_name(
    build_modules: ModuleBuilder,
) -> None:
    modules = build_modules(
        alpha="""
            from __future__ import annotations


            class Repo:
                origin = "alpha"
        """,
        beta="""
            from __future__ import annotations


            class Repo:
                origin = "beta"


            class Consumer:
                def __init__(self, repo: Repo) -> None:
                    self.repo = repo
        """,
    )
    alpha_repo = modules["alpha"].Repo
    beta_repo = modules["beta"].Repo
    consumer = modules["beta"].Consumer

    for visible in ([alpha_repo, beta_repo], [beta_repo, alpha_repo]):
        (dependency,) = plan_constructor_dependencies(consumer, visible)
        assert dependency.token is beta_repo
        assert dependency.annotation is beta_repo
        assert dependency.name == "repo"
        assert dependency.positional
        assert not dependency.optional


def test_a_name_the_defining_module_lacks_falls_through_to_the_visible_tokens(
    build_modules: ModuleBuilder,
) -> None:
    modules = build_modules(
        alpha="""
            from __future__ import annotations


            class Repo:
                origin = "alpha"
        """,
        gamma="""
            from __future__ import annotations


            class Consumer:
                def __init__(self, first: Repo, second: Repo) -> None:
                    self.first = first
                    self.second = second
        """,
    )
    alpha_repo = modules["alpha"].Repo

    dependencies = plan_constructor_dependencies(modules["gamma"].Consumer, [alpha_repo])

    assert [dependency.token for dependency in dependencies] == [alpha_repo, alpha_repo]


def test_two_visible_tokens_sharing_a_bare_name_are_reported_as_ambiguous(
    build_modules: ModuleBuilder,
) -> None:
    modules = build_modules(
        alpha="""
            from __future__ import annotations


            class Repo:
                origin = "alpha"
        """,
        beta="""
            from __future__ import annotations


            class Repo:
                origin = "beta"
        """,
        gamma="""
            from __future__ import annotations


            class Consumer:
                def __init__(self, first: Repo, second: Repo) -> None:
                    self.first = first
                    self.second = second
        """,
    )
    visible = [modules["alpha"].Repo, modules["beta"].Repo]

    with pytest.raises(ProviderResolutionError) as error:
        plan_constructor_dependencies(modules["gamma"].Consumer, visible)

    message = str(error.value)
    assert "Consumer" in message
    assert "'first'" in message
    assert "ambiguous" in message
    assert modules["alpha"].Repo.__module__ in message
    assert modules["beta"].Repo.__module__ in message


def test_an_inherited_constructor_is_read_in_the_module_that_defines_it(
    build_modules: ModuleBuilder,
) -> None:
    modules = build_modules(
        base="""
            from __future__ import annotations

            from typing import Annotated

            from bustan.common.decorators.injectable import Inject
            from bustan.core.ioc.tokens import InjectionToken

            CONFIG = InjectionToken("CONFIG")

            type Alias = dict


            class Helper:
                pass


            class MarkerBase:
                def __init__(
                    self, helper: Helper, cfg: Annotated[object, Inject(CONFIG)]
                ) -> None:
                    self.helper = helper
                    self.cfg = cfg


            class AliasBase:
                def __init__(self, value: Annotated[Alias, Inject(CONFIG)]) -> None:
                    self.value = value
        """,
        child="""
            from __future__ import annotations

            from .base import AliasBase, MarkerBase


            class MarkerChild(MarkerBase):
                pass


            class AliasChild(AliasBase):
                pass
        """,
    )
    base = modules["base"]
    child = modules["child"]

    marker = plan_constructor_dependencies(child.MarkerChild, [base.Helper, base.CONFIG])
    assert [dependency.name for dependency in marker] == ["helper", "cfg"]
    assert marker[0].token is base.Helper
    assert marker[1].token is base.CONFIG

    (alias,) = plan_constructor_dependencies(child.AliasChild, [base.CONFIG])
    assert alias.token is base.CONFIG
    assert alias.annotation is base.Alias


@pytest.mark.parametrize(
    ("target", "optional"),
    [
        (UsesDep, False),
        (UsesOptional, True),
        (UsesPipeNone, True),
        (UsesPipeNoneWithOptionalDep, True),
        (UsesPlainWithOptionalDep, True),
    ],
)
def test_optional_annotations_unwrap_to_the_type_that_is_actually_injected(
    target: type[object], optional: bool
) -> None:
    (dependency,) = plan_constructor_dependencies(target, [Dep])

    assert dependency.token is Dep
    assert dependency.annotation is Dep
    assert dependency.optional is optional


def test_a_union_without_none_is_left_as_the_token() -> None:
    (dependency,) = plan_constructor_dependencies(UsesUnionWithoutNone, [Dep])

    assert dependency.token == Dep | Other
    assert not dependency.optional


def test_a_union_of_several_types_with_none_is_rejected() -> None:
    with pytest.raises(ProviderResolutionError) as error:
        plan_constructor_dependencies(UsesUnionOfManyWithNone, [Dep, Other])

    assert "exactly one type" in str(error.value)


@pytest.mark.parametrize(
    "target",
    [DefaultedScalar, DefaultedUnannotated, DefaultedUnionNone, DefaultedOptionalDep],
)
def test_a_parameter_whose_token_is_invisible_is_left_to_its_default(
    target: type[object],
) -> None:
    assert plan_constructor_dependencies(target, [Dep]) == ()


def test_a_defaulted_parameter_is_still_injected_when_its_token_is_visible() -> None:
    (dependency,) = plan_constructor_dependencies(DefaultedVisibleDep, [Dep])

    assert dependency.token is Dep


def test_the_visibility_mapping_may_be_passed_directly() -> None:
    (dependency,) = plan_constructor_dependencies(DefaultedVisibleDep, {Dep: "any-module"})

    assert dependency.token is Dep


def test_an_unhashable_token_with_a_default_is_left_to_its_default() -> None:
    assert plan_constructor_dependencies(DefaultedUnhashableToken, {Dep: "any-module"}) == ()


def test_a_container_token_is_planned_even_though_no_module_declares_it() -> None:
    (dependency,) = plan_constructor_dependencies(DefaultedContainerToken, [])

    assert dependency.token is REQUEST


def test_a_second_inject_marker_is_rejected_rather_than_winning() -> None:
    with pytest.raises(ProviderResolutionError) as error:
        plan_constructor_dependencies(DuplicateInject, [])

    message = str(error.value)
    assert "'value'" in message
    assert "Inject markers" in message


def test_a_parameter_without_an_annotation_or_a_default_is_rejected() -> None:
    with pytest.raises(ProviderResolutionError) as error:
        plan_constructor_dependencies(Unannotated, [])

    assert "no type annotation" in str(error.value)


@pytest.mark.parametrize("target", [Variadic, VariadicKeywords])
def test_variadic_parameters_are_rejected(target: type[object]) -> None:
    with pytest.raises(ProviderResolutionError) as error:
        plan_constructor_dependencies(target, [Dep])

    assert "variadic" in str(error.value)


@pytest.mark.parametrize("target", [HeaderMap, CustomError])
def test_a_c_implemented_constructor_raises_a_framework_error(target: type[object]) -> None:
    with pytest.raises(ProviderResolutionError) as error:
        plan_constructor_dependencies(target, [])

    assert target.__name__ in str(error.value)


def test_a_malformed_string_annotation_raises_a_framework_error(
    build_modules: ModuleBuilder,
) -> None:
    modules = build_modules(
        malformed="""
            from __future__ import annotations


            class BadAnnotation:
                def __init__(self, dep: "List[") -> None:
                    self.dep = dep
        """
    )

    with pytest.raises(ProviderResolutionError) as error:
        plan_constructor_dependencies(modules["malformed"].BadAnnotation, [])

    message = str(error.value)
    assert "BadAnnotation" in message
    assert "'dep'" in message


def test_the_instance_parameter_is_skipped_by_position_not_by_name(
    build_modules: ModuleBuilder,
) -> None:
    modules = build_modules(
        renamed="""
            from __future__ import annotations


            class Dep:
                pass


            class NamesInstanceThis:
                def __init__(this, dep: Dep) -> None:
                    this.dep = dep


            class PositionalOnlyInstance:
                def __init__(instance, dep: Dep, /) -> None:
                    instance.dep = dep
        """
    )
    renamed = modules["renamed"]

    for target in (renamed.NamesInstanceThis, renamed.PositionalOnlyInstance):
        (dependency,) = plan_constructor_dependencies(target, [renamed.Dep])
        assert dependency.name == "dep"
        assert dependency.token is renamed.Dep
        assert dependency.positional


def test_a_parameter_after_one_left_to_its_default_is_passed_by_keyword(
    build_modules: ModuleBuilder,
) -> None:
    modules = build_modules(
        shifted="""
            from __future__ import annotations


            class Dep:
                pass


            class Shifted:
                def __init__(self, retries: int = 3, dep: Dep = None) -> None:
                    self.retries = retries
                    self.dep = dep
        """
    )
    shifted = modules["shifted"]

    (dependency,) = plan_constructor_dependencies(shifted.Shifted, [shifted.Dep])

    assert dependency.name == "dep"
    assert not dependency.positional


def test_a_positional_only_parameter_after_one_left_to_its_default_is_rejected(
    build_modules: ModuleBuilder,
) -> None:
    modules = build_modules(
        pinned="""
            from __future__ import annotations


            class Dep:
                pass


            class Pinned:
                def __init__(self, retries: int = 3, dep: Dep = None, /) -> None:
                    self.retries = retries
                    self.dep = dep
        """
    )
    pinned = modules["pinned"]

    with pytest.raises(ProviderResolutionError) as error:
        plan_constructor_dependencies(pinned.Pinned, [pinned.Dep])

    assert "positional-only" in str(error.value)


def test_a_keyword_only_parameter_is_not_marked_positional() -> None:
    (dependency,) = plan_constructor_dependencies(UsesKeywordOnlyDep, [Dep])

    assert not dependency.positional


def test_a_class_with_no_constructor_of_its_own_needs_nothing() -> None:
    assert plan_constructor_dependencies(Bare, [Dep]) == ()


def test_dependencies_are_planned_from_new_when_init_is_inherited_from_object() -> None:
    (dependency,) = plan_constructor_dependencies(NewOnly, [Dep])

    assert dependency.name == "dep"
    assert dependency.token is Dep
    assert dependency.positional


def test_the_namespace_reports_the_names_it_can_resolve() -> None:
    hidden = type("Hidden", (), {})
    namespace = _ConstructorNamespace(UsesDep.__init__, [hidden, hidden, InjectionToken("T")])

    assert namespace["Hidden"] is hidden
    assert namespace["Dep"] is Dep
    assert "Hidden" in set(namespace)
    assert len(namespace) == len(set(namespace))

    with pytest.raises(KeyError):
        namespace["Missing"]


def test_a_quoted_annotation_is_resolved_through_its_extra_layer_of_quoting(
    build_modules: ModuleBuilder,
) -> None:
    modules = build_modules(
        quoted="""
            from __future__ import annotations

            from typing import Annotated

            from bustan.common.decorators.injectable import OptionalDep


            class Consumer:
                def __init__(
                    self, dep: "Dep", other: Annotated["Dep", OptionalDep()]
                ) -> None:
                    self.dep = dep
                    self.other = other


            class Dep:
                pass
        """
    )
    quoted = modules["quoted"]

    dependencies = plan_constructor_dependencies(quoted.Consumer, [quoted.Dep])

    assert [dependency.token for dependency in dependencies] == [quoted.Dep, quoted.Dep]
    assert [dependency.optional for dependency in dependencies] == [False, True]


def test_an_annotation_that_only_ever_names_another_name_is_rejected(
    build_modules: ModuleBuilder,
) -> None:
    modules = build_modules(
        circular="""
            from __future__ import annotations

            Loop = "Loop"


            class Consumer:
                def __init__(self, dep: Loop) -> None:
                    self.dep = dep
        """
    )

    with pytest.raises(ProviderResolutionError) as error:
        plan_constructor_dependencies(modules["circular"].Consumer, [])

    assert "never resolves" in str(error.value)


def test_annotated_metadata_that_is_not_a_marker_is_ignored() -> None:
    (dependency,) = plan_constructor_dependencies(UsesAnnotatedNote, [Dep])

    assert dependency.token is Dep
    assert not dependency.optional


def test_a_constructor_the_interpreter_cannot_describe_raises_a_framework_error(
    build_modules: ModuleBuilder,
) -> None:
    modules = build_modules(
        awkward="""
            from __future__ import annotations

            import math


            class Uninspectable:
                __init__ = math.log
        """
    )

    with pytest.raises(ProviderResolutionError) as error:
        plan_constructor_dependencies(modules["awkward"].Uninspectable, [])

    assert "Uninspectable" in str(error.value)


def test_a_constructor_without_an_instance_parameter_keeps_every_parameter(
    build_modules: ModuleBuilder,
) -> None:
    modules = build_modules(
        keyword_only="""
            from __future__ import annotations


            class Dep:
                pass


            class NoInstanceParameter:
                def __init__(*, dep: Dep) -> None:
                    pass
        """
    )
    keyword_only = modules["keyword_only"]

    (dependency,) = plan_constructor_dependencies(
        keyword_only.NoInstanceParameter, [keyword_only.Dep]
    )

    assert dependency.name == "dep"
    assert not dependency.positional
