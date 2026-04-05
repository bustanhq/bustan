"""Unit tests for public decorators and pipeline metadata attachment."""

import pytest
from typing import cast

from bustan import (
    ExceptionFilter,
    Guard,
    Interceptor,
    Pipe,
    Controller,
    Get,
    Injectable,
    Module,
    Post,
    UseFilters,
    UseGuards,
    UseInterceptors,
    UsePipes,
)
from bustan.errors import InvalidControllerError, InvalidPipelineError, InvalidProviderError, RouteDefinitionError
from bustan.metadata import (
    ControllerMetadata,
    ModuleMetadata,
    PipelineMetadata,
    ProviderMetadata,
    ProviderScope,
    RouteMetadata,
    get_controller_metadata,
    get_controller_pipeline_metadata,
    get_handler_pipeline_metadata,
    get_module_metadata,
    get_provider_metadata,
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