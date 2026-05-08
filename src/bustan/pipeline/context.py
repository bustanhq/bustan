"""Context objects shared across request pipeline stages."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from ..platform.http.abstractions import HttpRequest, as_http_request
from ..platform.http.metadata import ControllerRouteDefinition

if TYPE_CHECKING:
    from ..core.ioc.container import Container
    from ..core.module.dynamic import ModuleKey


@dataclass(frozen=True, slots=True)
class _ParameterExecutionState:
    """Internal per-parameter execution data attached to an execution context."""

    name: str
    source: str
    annotation: object
    value: object
    validation_mode: str = "auto"
    validate_custom_decorators: bool = False


class ArgumentsHost:
    """Public wrapper around transport arguments passed through the pipeline."""

    def __init__(
        self,
        args: tuple[object, ...],
        *,
        context_type: Literal["http"] = "http",
    ) -> None:
        self._args = args
        self._context_type = context_type

    def get_args(self) -> tuple[object, ...]:
        return self._args

    def get_arg_by_index(self, index: int) -> object | None:
        if index < 0 or index >= len(self._args):
            return None
        return self._args[index]

    def get_type(self) -> Literal["http"]:
        return self._context_type

    def switch_to_http(self) -> HttpArgumentsHost:
        return HttpArgumentsHost(self)


class HttpArgumentsHost:
    """HTTP-specific view over a generic arguments host."""

    def __init__(self, host: ArgumentsHost) -> None:
        self._host = host

    def get_request(self) -> object | None:
        return self._host.get_arg_by_index(0)

    def get_response(self) -> object | None:
        return self._host.get_arg_by_index(1)

    def get_next(self) -> object | None:
        return self._host.get_arg_by_index(2)


class ExecutionContext(ArgumentsHost):
    """Public request execution context shared across guards and filters."""

    def __init__(
        self,
        args: tuple[object, ...],
        *,
        handler: object,
        controller_type: type[object],
        module: ModuleKey,
        controller: object,
        container: Container,
        route: ControllerRouteDefinition | None = None,
        route_contract: object | None = None,
        policy_plan: object | None = None,
        parameter_state: _ParameterExecutionState | None = None,
    ) -> None:
        super().__init__(args)
        self._handler = handler
        self._controller_type = controller_type
        self._module = module
        self._controller = controller
        self._container = container
        self._route = route
        self._route_contract = route_contract
        self._policy_plan = policy_plan
        self._parameter_state = parameter_state

    @classmethod
    def create_http(
        cls,
        *,
        request: HttpRequest | object,
        response: object | None,
        handler: object,
        controller_cls: type[object],
        module: ModuleKey,
        controller: object,
        container: Container,
        route: ControllerRouteDefinition | None = None,
        route_contract: object | None = None,
        policy_plan: object | None = None,
    ) -> ExecutionContext:
        return cls(
            (request, response),
            handler=handler,
            controller_type=controller_cls,
            module=module,
            controller=controller,
            container=container,
            route=route,
            route_contract=route_contract,
            policy_plan=policy_plan,
        )

    def get_handler(self) -> object:
        return self._handler

    def get_class(self) -> type[object]:
        return self._controller_type

    def get_module(self) -> ModuleKey:
        return self._module

    def get_route_contract(self) -> object | None:
        return self._route_contract

    def get_policy_plan(self) -> object | None:
        return self._policy_plan

    def get_principal(self) -> object | None:
        request = self.request
        if request is None:
            return None
        return getattr(getattr(request, "state", object()), "principal", None)

    def with_parameter(
        self,
        *,
        name: str,
        source: str,
        annotation: object,
        value: object,
        validation_mode: str = "auto",
        validate_custom_decorators: bool = False,
    ) -> ExecutionContext:
        return ExecutionContext(
            self.get_args(),
            handler=self._handler,
            controller_type=self._controller_type,
            module=self._module,
            controller=self._controller,
            container=self._container,
            route=self._route,
            route_contract=self._route_contract,
            policy_plan=self._policy_plan,
            parameter_state=_ParameterExecutionState(
                name=name,
                source=source,
                annotation=annotation,
                value=value,
                validation_mode=validation_mode,
                validate_custom_decorators=validate_custom_decorators,
            ),
        )

    def with_parameter_value(self, value: object) -> ExecutionContext:
        if self._parameter_state is None:
            return self

        return ExecutionContext(
            self.get_args(),
            handler=self._handler,
            controller_type=self._controller_type,
            module=self._module,
            controller=self._controller,
            container=self._container,
            route=self._route,
            route_contract=self._route_contract,
            policy_plan=self._policy_plan,
            parameter_state=replace(self._parameter_state, value=value),
        )

    @property
    def request(self) -> HttpRequest | None:
        request = self.get_arg_by_index(0)
        if request is None:
            return None
        return as_http_request(request)

    @property
    def response(self) -> object | None:
        return self.get_arg_by_index(1)

    @property
    def module(self) -> ModuleKey:
        return self._module

    @property
    def controller_type(self) -> type[object]:
        return self._controller_type

    @property
    def controller(self) -> object:
        return self._controller

    @property
    def container(self) -> Container:
        return self._container

    @property
    def route(self) -> ControllerRouteDefinition | None:
        return self._route

    @property
    def route_contract(self) -> object | None:
        return self._route_contract

    @property
    def policy_plan(self) -> object | None:
        return self._policy_plan

    @property
    def parameter_name(self) -> str | None:
        if self._parameter_state is None:
            return None
        return self._parameter_state.name

    @property
    def parameter_source(self) -> str | None:
        if self._parameter_state is None:
            return None
        return self._parameter_state.source

    @property
    def parameter_annotation(self) -> object | None:
        if self._parameter_state is None:
            return None
        return self._parameter_state.annotation

    @property
    def parameter_value(self) -> object | None:
        if self._parameter_state is None:
            return None
        return self._parameter_state.value

    @property
    def name(self) -> str | None:
        return self.parameter_name

    @property
    def source(self) -> str | None:
        return self.parameter_source

    @property
    def annotation(self) -> object | None:
        return self.parameter_annotation

    @property
    def value(self) -> object | None:
        return self.parameter_value

    @property
    def validation_mode(self) -> str:
        if self._parameter_state is None:
            return "auto"
        return self._parameter_state.validation_mode

    @property
    def validate_custom_decorators(self) -> bool:
        if self._parameter_state is None:
            return False
        return self._parameter_state.validate_custom_decorators

    @property
    def metatype(self) -> type[object] | None:
        annotation = self.parameter_annotation
        return annotation if isinstance(annotation, type) else None

    @property
    def execution_context(self) -> ExecutionContext:
        return self


class RequestContext(ExecutionContext):
    """Compatibility shim over ``ExecutionContext`` for legacy imports."""

    def __init__(
        self,
        *,
        request: HttpRequest | object,
        module: ModuleKey,
        controller_type: type[object],
        controller: object,
        route: ControllerRouteDefinition,
        container: Container,
        route_contract: object | None = None,
        policy_plan: object | None = None,
    ) -> None:
        super().__init__(
            (request, None),
            handler=route.handler,
            controller_type=controller_type,
            module=module,
            controller=controller,
            container=container,
            route=route,
            route_contract=route_contract,
            policy_plan=policy_plan,
        )

    @property
    def request(self) -> HttpRequest:
        request = super().request
        assert request is not None
        return request

    @property
    def route(self) -> ControllerRouteDefinition:
        route = super().route
        assert route is not None
        return route


@dataclass(frozen=True, slots=True)
class ParameterContext:
    """Compatibility shim over parameter-scoped execution context state."""

    request_context: ExecutionContext
    name: str
    source: str
    annotation: object
    value: object
    validation_mode: str = "auto"
    validate_custom_decorators: bool = False

    @property
    def execution_context(self) -> ExecutionContext:
        return self.request_context

    @property
    def parameter_name(self) -> str:
        return self.name

    @property
    def parameter_source(self) -> str:
        return self.source

    @property
    def parameter_annotation(self) -> object:
        return self.annotation

    @property
    def parameter_value(self) -> object:
        return self.value

    @property
    def metatype(self) -> type[object] | None:
        """Return the resolved type annotation when it is a concrete type."""
        return self.annotation if isinstance(self.annotation, type) else None

    def with_parameter_value(self, value: object) -> ParameterContext:
        return replace(self, value=value)


@dataclass(frozen=True, slots=True)
class HandlerContext:
    """Compatibility shim over handler invocation state."""

    request_context: ExecutionContext
    arguments: tuple[object, ...]
    keyword_arguments: Mapping[str, object]

    @property
    def execution_context(self) -> ExecutionContext:
        return self.request_context
