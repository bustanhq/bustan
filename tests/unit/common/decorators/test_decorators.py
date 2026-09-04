"""Unit tests for public decorators and pipeline metadata attachment."""

from dataclasses import FrozenInstanceError, fields
from typing import Any, cast

import pytest

from bustan import (
    Controller,
    ExceptionFilter,
    Get,
    Guard,
    Injectable,
    Interceptor,
    Module,
    Pipe,
    Post,
    UseFilters,
    UseGuards,
    UseInterceptors,
    UsePipes,
)
from bustan.common.decorators.injectable import ProviderMetadata, get_provider_metadata
from bustan.common.types import ProviderScope
from bustan.core.errors import (
    InvalidControllerError,
    InvalidPipelineError,
    InvalidProviderError,
    RouteDefinitionError,
)
from bustan.core.module.metadata import (
    ModuleMetadata,
    get_module_metadata,
)
from bustan.pipeline.metadata import (
    PipelineMetadata,
    get_controller_pipeline_metadata,
    get_handler_pipeline_metadata,
)
from bustan.platform.http.metadata import (
    ControllerMetadata,
    RouteMetadata,
    get_controller_metadata,
    get_route_metadata,
)


def test_decorators_attach_expected_metadata() -> None:
    @Injectable
    class UserService:
        pass

    @Controller("users")
    class UserController:
        pass

    @Module(
        controllers=[UserController],
        providers=[UserService],
        exports=[UserService],
    )
    class UserModule:
        pass

    assert get_provider_metadata(UserService) == ProviderMetadata(scope=ProviderScope.SINGLETON)
    assert get_controller_metadata(UserController) == ControllerMetadata(prefix="/users")
    assert get_module_metadata(UserModule) == ModuleMetadata(
        imports=(),
        controllers=(UserController,),
        providers=(UserService,),
        exports=(UserService,),
    )


def test_route_decorator_attaches_normalized_metadata() -> None:
    class UserController:
        @Get("users/{user_id}/")
        def read_user(self) -> None:
            return None

    assert get_route_metadata(UserController.read_user) == RouteMetadata(
        method="GET",
        path="/users/{user_id}",
        name="read_user",
    )


def test_duplicate_route_decorators_fail_with_clear_error() -> None:
    with pytest.raises(RouteDefinitionError, match="already has route metadata"):

        class UserController:
            @Get("/users")
            @Post("/users")
            def create_user(self) -> None:
                return None


def test_controller_prefix_must_be_a_string() -> None:
    with pytest.raises(InvalidControllerError, match="Controller prefix must be a string"):
        Controller(prefix=cast(str, None))


def test_injectable_rejects_unsupported_scopes() -> None:
    with pytest.raises(InvalidProviderError, match="Unsupported provider scope"):
        Injectable(scope="scoped")


def test_pipeline_decorators_attach_controller_and_handler_metadata() -> None:
    class AuthGuard(Guard):
        pass

    class TrimPipe(Pipe):
        pass

    class EnvelopeInterceptor(Interceptor):
        pass

    class ValueErrorFilter(ExceptionFilter):
        pass

    controller_guard = AuthGuard()
    route_pipe = TrimPipe()
    controller_interceptor = EnvelopeInterceptor()
    route_filter = ValueErrorFilter()

    @UseGuards(controller_guard)
    @UseInterceptors(controller_interceptor)
    @Controller("/users")
    class UserController:
        @UsePipes(route_pipe)
        @UseFilters(route_filter)
        @Get("/")
        def list_users(self) -> None:
            return None

    assert get_controller_pipeline_metadata(UserController) == PipelineMetadata(
        guards=(controller_guard,),
        pipes=(),
        interceptors=(controller_interceptor,),
        filters=(),
    )
    assert get_handler_pipeline_metadata(UserController.list_users) == PipelineMetadata(
        guards=(),
        pipes=(route_pipe,),
        interceptors=(),
        filters=(route_filter,),
    )


def test_pipeline_decorators_require_at_least_one_component() -> None:
    with pytest.raises(InvalidPipelineError, match="requires at least one component"):
        UseGuards()


def test_controller_and_route_decorators_validate_invalid_inputs() -> None:
    with pytest.raises(InvalidControllerError, match="Unsupported controller scope"):
        Controller("/users", scope="request-ish")

    with pytest.raises(InvalidControllerError, match="only decorate classes"):
        Controller("/users")(cast(Any, lambda: None))

    with pytest.raises(RouteDefinitionError, match="Route method must be a string"):
        from bustan.common.decorators.route import Route

        Route(cast(str, None))

    with pytest.raises(RouteDefinitionError, match="cannot be empty"):
        from bustan.common.decorators.route import Route

        Route("   ")

    with pytest.raises(RouteDefinitionError, match="invalid characters"):
        from bustan.common.decorators.route import Route

        Route("GE T")

    with pytest.raises(RouteDefinitionError, match="decorate callables"):
        from bustan.common.decorators.route import Get

        Get("/users")(cast(Any, 1))


def test_injectable_metadata_is_frozen_and_carries_only_the_scope() -> None:
    # Provider metadata that could hold a token and a target was a second, editable copy
    # of an identity the class already carries, and the two could be made to disagree.
    @Injectable(scope=ProviderScope.REQUEST)
    class Service:
        pass

    metadata = get_provider_metadata(Service)
    assert metadata == ProviderMetadata(scope=ProviderScope.REQUEST)
    assert [field.name for field in fields(ProviderMetadata)] == ["scope"]

    with pytest.raises(FrozenInstanceError):
        cast(Any, metadata).scope = ProviderScope.SINGLETON


def test_injectable_metadata_is_read_from_the_class_it_was_written_on() -> None:
    @Injectable(scope=ProviderScope.REQUEST)
    class Base:
        pass

    class Derived(Base):
        pass

    assert get_provider_metadata(Base) == ProviderMetadata(scope=ProviderScope.REQUEST)
    assert get_provider_metadata(Derived) is None
    assert get_provider_metadata(Derived, inherit=True) == get_provider_metadata(Base)


def test_injectable_refuses_a_scope_it_does_not_support() -> None:
    with pytest.raises(InvalidProviderError, match="Unsupported provider scope"):
        Injectable(scope="Request")

    with pytest.raises(InvalidProviderError, match="only decorate classes"):
        Injectable(cast(Any, lambda: None))
