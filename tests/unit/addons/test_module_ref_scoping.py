"""The module a reference resolves against, and what a non-strict lookup is allowed to find.

A reference is transient, so one is built for each consumer and belongs to the module
that consumer was declared in. That is the whole of what these tests pin: a service in a
child module sees its own private providers through the reference exactly as its own
constructor does, and widening the lookup searches every module rather than falling back
to the root, which could only ever see what the root already sees.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from starlette.testclient import TestClient

from bustan import (
    Controller,
    DiscoveryModule,
    Get,
    Injectable,
    Module,
    ModuleRef,
    create_app,
    create_app_context,
)
from bustan.errors import ProviderResolutionError


@Injectable()
class PrivateInChild:
    """A provider its own module keeps to itself."""


@Injectable()
class ChildService:
    def __init__(self, module_ref: ModuleRef) -> None:
        self.module_ref = module_ref


@Module(
    imports=[DiscoveryModule],
    providers=[PrivateInChild, ChildService],
    exports=[ChildService],
)
class ChildModule:
    pass


@Module(imports=[ChildModule, DiscoveryModule])
class AppModule:
    pass


def test_a_reference_belongs_to_the_module_of_the_provider_that_received_it() -> None:
    service = create_app_context(AppModule).get(ChildService)

    assert service.module_ref.module_key is ChildModule
    assert isinstance(service.module_ref.get(PrivateInChild), PrivateInChild)
    assert isinstance(service.module_ref.get(PrivateInChild, strict=False), PrivateInChild)


def test_a_reference_asked_of_the_application_belongs_to_the_root_module() -> None:
    context = create_app_context(AppModule)

    assert context.get(ModuleRef).module_key is AppModule


def test_a_reference_belongs_to_the_module_of_the_controller_that_received_it() -> None:
    @Injectable()
    class PrivateInFeature:
        pass

    @Controller("/feature")
    class FeatureController:
        def __init__(self, module_ref: ModuleRef) -> None:
            self.module_ref = module_ref

        @Get("/")
        def read(self) -> dict[str, str]:
            return {"resolved": type(self.module_ref.get(PrivateInFeature)).__name__}

    @Module(
        imports=[DiscoveryModule],
        controllers=[FeatureController],
        providers=[PrivateInFeature],
    )
    class FeatureModule:
        pass

    @Module(imports=[FeatureModule, DiscoveryModule])
    class RootModule:
        pass

    with TestClient(cast(Any, create_app(RootModule))) as client:
        body = client.get("/feature/").json()

    assert body == {"resolved": "PrivateInFeature"}


def test_a_non_strict_lookup_searches_every_module_rather_than_the_root() -> None:
    @Injectable()
    class SiblingPrivate:
        pass

    @Module(providers=[SiblingPrivate])
    class SiblingModule:
        pass

    @Module(imports=[SiblingModule, DiscoveryModule])
    class RootModule:
        pass

    context = create_app_context(RootModule)
    module_ref = context.get(ModuleRef)

    assert isinstance(module_ref.get(SiblingPrivate, strict=False), SiblingPrivate)
    with pytest.raises(ProviderResolutionError, match="is not available to"):
        module_ref.get(SiblingPrivate)


def test_a_non_strict_lookup_refuses_to_choose_between_two_modules() -> None:
    @Injectable()
    class Contested:
        pass

    @Module(providers=[Contested])
    class FirstModule:
        pass

    @Module(providers=[Contested])
    class SecondModule:
        pass

    @Module(imports=[FirstModule, SecondModule, DiscoveryModule])
    class RootModule:
        pass

    module_ref = create_app_context(RootModule).get(ModuleRef)

    with pytest.raises(ProviderResolutionError, match="declared by more than one module"):
        module_ref.get(Contested, strict=False)


def test_a_non_strict_lookup_prefers_what_the_reference_s_own_module_can_see() -> None:
    # Two modules declare the token and the reference's own module can see one of them,
    # so there is nothing to choose between: the module answers, as it would strictly.
    @Injectable()
    class Contested:
        pass

    @Module(providers=[Contested], exports=[Contested])
    class VisibleModule:
        pass

    @Module(providers=[Contested])
    class HiddenModule:
        pass

    @Module(imports=[VisibleModule, HiddenModule, DiscoveryModule])
    class RootModule:
        pass

    context = create_app_context(RootModule)
    module_ref = context.get(ModuleRef)

    assert module_ref.get(Contested, strict=False) is context.get(Contested)


def test_a_non_strict_lookup_reports_a_token_no_module_declares() -> None:
    module_ref = create_app_context(AppModule).get(ModuleRef)

    with pytest.raises(ProviderResolutionError, match="is not available to"):
        module_ref.get("nothing-declares-this", strict=False)


def test_a_reference_creates_instances_against_the_module_that_received_it() -> None:
    @Injectable()
    class NeedsPrivate:
        def __init__(self, private: PrivateInChild) -> None:
            self.private = private

    service = create_app_context(AppModule).get(ChildService)
    created = service.module_ref.create(NeedsPrivate)

    assert isinstance(created, NeedsPrivate)
