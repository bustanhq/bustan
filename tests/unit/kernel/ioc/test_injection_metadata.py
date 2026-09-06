"""Unit tests for Inject, OptionalDep, and special DI tokens."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Any, cast

import pytest

from bustan import (
    APPLICATION,
    REQUEST,
    Inject,
    Injectable,
    InjectionToken,
    Module,
    OptionalDep,
    create_app_context,
)
from bustan.kernel.errors import ProviderResolutionError
from bustan.kernel.ioc.container import build_container
from bustan.kernel.module.graph import build_module_graph

if TYPE_CHECKING:
    from tests.conftest import HttpRequestFactory

CONFIG_TOKEN = InjectionToken[str]("CONFIG")
MISSING_TOKEN = InjectionToken[object]("MISSING")


class Tokens(StrEnum):
    """A string enum token set, whose members equal the bare strings they are written as."""

    DB = "db"


def test_explicit_inject_overrides_annotation_based_resolution() -> None:
    @Injectable
    class ConfigConsumer:
        def __init__(self, config: Annotated[str, Inject(CONFIG_TOKEN)]) -> None:
            self.config = config

    @Module(
        providers=[ConfigConsumer, {"provide": CONFIG_TOKEN, "use_value": "configured"}],
        exports=[ConfigConsumer],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    consumer = cast(Any, container.resolve(ConfigConsumer, module=AppModule))

    assert consumer.config == "configured"


def test_optional_dependency_returns_none_only_when_marked_optional() -> None:
    @Injectable
    class OptionalConsumer:
        def __init__(
            self,
            maybe: Annotated[object | None, Inject(MISSING_TOKEN), OptionalDep()],
        ) -> None:
            self.maybe = maybe

    @Injectable
    class RequiredConsumer:
        def __init__(self, maybe: Annotated[object, Inject(MISSING_TOKEN)]) -> None:
            self.maybe = maybe

    @Module(providers=[OptionalConsumer])
    class OptionalModule:
        pass

    @Module(providers=[RequiredConsumer])
    class RequiredModule:
        pass

    container = build_container(build_module_graph(OptionalModule))
    optional_consumer = cast(Any, container.resolve(OptionalConsumer, module=OptionalModule))

    assert optional_consumer.maybe is None

    # The same token without the marker is a dependency nothing can supply, and a
    # graph containing one is refused where it is declared rather than where it is used.
    with pytest.raises(ProviderResolutionError, match="MISSING"):
        build_container(build_module_graph(RequiredModule))


def test_special_request_token_is_rejected_outside_request_scope() -> None:
    @Injectable
    class RequestAwareService:
        def __init__(self, request: Annotated[object, Inject(REQUEST)]) -> None:
            self.request = request

    @Module(providers=[RequestAwareService])
    class AppModule:
        pass

    with pytest.raises(ProviderResolutionError, match="REQUEST"):
        build_container(build_module_graph(AppModule))


def test_special_request_token_resolves_within_request_scope(
    build_http_request: HttpRequestFactory,
) -> None:
    @Injectable(scope="request")
    class RequestAwareService:
        def __init__(self, request: Annotated[object, Inject(REQUEST)]) -> None:
            self.request = request

    @Module(providers=[RequestAwareService], exports=[RequestAwareService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    request = build_http_request(path="/request-aware")

    service = cast(Any, container.resolve(RequestAwareService, module=AppModule, request=request))

    assert service.request is request


def test_application_token_resolves_in_application_context() -> None:
    @Injectable
    class AppAwareService:
        def __init__(self, app: Annotated[object, Inject(APPLICATION)]) -> None:
            self.app = app

    @Module(providers=[AppAwareService], exports=[AppAwareService])
    class AppModule:
        pass

    context = create_app_context(AppModule)
    service = context.get(AppAwareService)

    assert service.app is context


def test_two_annotations_naming_equal_tokens_of_different_types_stay_apart() -> None:
    # Annotated memoizes a subscription on its arguments, so two annotations whose
    # markers compare equal are one object carrying one token. A string enum member
    # equals the bare string it is written as, and the second parameter used to be
    # handed the first one's provider before the container was ever consulted.
    assert Annotated[object, Inject(Tokens.DB)] is not Annotated[object, Inject("db")]

    @Injectable
    class FromEnum:
        pass

    @Injectable
    class FromStr:
        pass

    @Injectable
    class Consumer:
        def __init__(
            self,
            from_enum: Annotated[object, Inject(Tokens.DB)],
            from_str: Annotated[object, Inject("db")],
        ) -> None:
            self.from_enum = from_enum
            self.from_str = from_str

    # One module may not declare both, because two equal tokens of different types in
    # one providers list is refused where it is written. Declaring them apart is the
    # arrangement a user reaches for instead, and the one this defect survived in.
    @Module(
        providers=[{"provide": Tokens.DB, "use_class": FromEnum}],
        exports=[Tokens.DB],
    )
    class SharedModule:
        pass

    @Module(
        imports=[SharedModule],
        providers=[Consumer, {"provide": "db", "use_class": FromStr}],
        exports=[Consumer],
    )
    class FeatureModule:
        pass

    container = build_container(build_module_graph(FeatureModule))
    consumer = cast(Any, container.resolve(Consumer, module=FeatureModule))

    assert isinstance(consumer.from_enum, FromEnum)
    assert isinstance(consumer.from_str, FromStr)
    assert consumer.from_enum is not consumer.from_str


def test_two_annotations_naming_a_true_and_a_one_token_stay_apart() -> None:
    # True equals 1 and hashes with it, so a boolean token and the integer it equals
    # are the same pairing of traps as the string enum, without any enum in sight.
    assert Annotated[object, Inject(True)] is not Annotated[object, Inject(1)]

    @Injectable
    class Consumer:
        def __init__(
            self,
            from_bool: Annotated[str, Inject(True)],
            from_int: Annotated[str, Inject(1)],
        ) -> None:
            self.from_bool = from_bool
            self.from_int = from_int

    @Module(providers=[{"provide": True, "use_value": "bool-token"}], exports=[True])
    class SharedModule:
        pass

    @Module(
        imports=[SharedModule],
        providers=[Consumer, {"provide": 1, "use_value": "int-token"}],
        exports=[Consumer],
    )
    class FeatureModule:
        pass

    container = build_container(build_module_graph(FeatureModule))
    consumer = cast(Any, container.resolve(Consumer, module=FeatureModule))

    assert consumer.from_bool == "bool-token"
    assert consumer.from_int == "int-token"


def test_two_annotations_naming_the_same_token_are_still_one_annotation() -> None:
    # Memoization is what makes an annotation cheap to repeat, and telling equal tokens
    # of different types apart must not cost it: the same token written twice is still
    # one marker and one annotation object.
    assert Inject(Tokens.DB) == Inject(Tokens.DB)
    assert hash(Inject(Tokens.DB)) == hash(Inject(Tokens.DB))
    assert Annotated[object, Inject(Tokens.DB)] is Annotated[object, Inject(Tokens.DB)]
    assert Annotated[object, Inject("db")] is Annotated[object, Inject("db")]


def test_an_inject_marker_never_equals_a_marker_of_another_kind() -> None:
    assert Inject("db") != Inject(1)
    assert Inject("db") != OptionalDep()
    assert Inject("db") != "db"
