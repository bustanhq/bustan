"""What each stage of the request pipeline observes of the request it serves.

A guard decides before the controller exists and every later stage runs once it does, so
the two are handed different contexts, and a filter is handed the one belonging to the
stage the failure reached. Every stage of one request reaches the same response, which is
the one a provider injecting it is handed and the one merged into what the caller receives.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from starlette.testclient import TestClient

from bustan import (
    CallHandler,
    Controller,
    ExceptionFilter,
    ExecutionContext,
    Get,
    Guard,
    HttpRequest,
    HttpResponse,
    Injectable,
    Interceptor,
    Module,
    Pipe,
    Scope,
    UseFilters,
    UseGuards,
    UseInterceptors,
    UsePipes,
    create_app,
    create_param_decorator,
)


@Injectable(scope=Scope.REQUEST)
class ResponseProbe:
    """Keeps the response the container hands a provider built for the request."""

    def __init__(self, response: HttpResponse) -> None:
        self.response = response


class HandlerFailed(LookupError):
    """Raised where a test asks a handler or a constructor to fail."""


# The contexts the custom parameter below has been handed. It is declared here rather
# than inside its test because a handler's annotations are resolved against the module.
_PARAMETER_CONTEXTS: list[ExecutionContext] = []


def _observe_parameter(data: object | None, context: object) -> object:
    _PARAMETER_CONTEXTS.append(cast(ExecutionContext, context))
    return "observed"


Observed = create_param_decorator(_observe_parameter, name="Observed")


def _serve(module: type[object], *paths: str) -> list[Any]:
    with TestClient(cast(Any, create_app(module))) as client:
        return [client.get(path) for path in paths]


def _observed_module(seen: dict[str, Any], *, outcome: str) -> type[object]:
    """Return a module whose one route records the context each stage is handed.

    *outcome* is ``served``, ``failed`` for a handler that raises, or ``refused`` for a
    guard that turns the request away. The guard writes a header onto the response it is
    handed, so the response that header arrives on is the one the guard reached.
    """

    class ObservingGuard(Guard):
        def can_activate(self, context: ExecutionContext) -> bool:
            seen["guard"] = context
            cast(HttpResponse, context.response).headers["x-guard"] = "seen"
            return outcome != "refused"

    class ObservingInterceptor(Interceptor):
        async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
            seen["interceptor"] = context
            return await next.handle()

    class ObservingFilter(ExceptionFilter):
        def catch(self, exc: Exception, context: ExecutionContext) -> object:
            seen["filter"] = context
            return None

    @UseFilters(ObservingFilter())
    @UseInterceptors(ObservingInterceptor())
    @UseGuards(ObservingGuard())
    @Controller("/orders", scope=Scope.REQUEST)
    class OrdersController:
        def __init__(self, probe: ResponseProbe) -> None:
            self.probe = probe

        @Get("/")
        async def read(self) -> dict[str, str]:
            seen["controller"] = self
            if outcome == "failed":
                raise HandlerFailed("the handler failed")
            return {"status": "ok"}

    @Module(controllers=[OrdersController], providers=[ResponseProbe])
    class OrdersModule:
        pass

    return OrdersModule


def test_a_pipe_that_keeps_its_context_still_reads_the_parameter_it_was_called_for() -> None:
    kept: list[ExecutionContext] = []
    served: list[object] = []

    class KeepingPipe(Pipe):
        def transform(self, value: object, context: ExecutionContext) -> object:
            kept.append(context)
            return value

    @UsePipes(KeepingPipe())
    @Controller("/pairs")
    class PairsController:
        @Get("/")
        async def read(self, first: str, second: int) -> dict[str, object]:
            served.append(self)
            return {"first": first, "second": second}

    @Module(controllers=[PairsController])
    class PairsModule:
        pass

    [response] = _serve(PairsModule, "/pairs?first=a&second=2")

    assert response.json() == {"first": "a", "second": 2}
    # Read only after both parameters were piped, so a context shared between them
    # would name the second parameter twice.
    assert [(context.name, context.source, context.value) for context in kept] == [
        ("first", "query", "a"),
        ("second", "query", 2),
    ]
    first, second = kept
    [controller] = served
    assert first.controller is controller
    assert second.controller is controller
    assert first.response is second.response
    assert isinstance(first.response, HttpResponse)


def test_a_guard_and_an_interceptor_reach_one_response_from_their_own_stage() -> None:
    seen: dict[str, Any] = {}

    [response] = _serve(_observed_module(seen, outcome="served"), "/orders")

    guard, interceptor, controller = seen["guard"], seen["interceptor"], seen["controller"]
    assert response.status_code == 200
    # The guard decided before the controller existed; the interceptor runs once it does.
    assert guard.controller is None
    assert interceptor.controller is controller
    assert guard is not interceptor
    assert guard.response is interceptor.response
    assert guard.response is controller.probe.response
    assert response.headers["x-guard"] == "seen"
    assert "filter" not in seen


def test_a_filter_answering_a_handler_failure_is_handed_the_interceptors_context() -> None:
    seen: dict[str, Any] = {}

    [response] = _serve(_observed_module(seen, outcome="failed"), "/orders")

    assert response.status_code == 500
    assert seen["filter"] is seen["interceptor"]
    assert seen["filter"].controller is seen["controller"]
    assert seen["filter"].response is seen["guard"].response
    assert response.headers["x-guard"] == "seen"


def test_a_filter_answering_a_refusal_is_handed_the_guards_context() -> None:
    seen: dict[str, Any] = {}

    [response] = _serve(_observed_module(seen, outcome="refused"), "/orders")

    assert response.status_code == 403
    assert seen["filter"] is seen["guard"]
    assert seen["filter"].controller is None
    assert "controller" not in seen
    assert "interceptor" not in seen
    assert response.headers["x-guard"] == "seen"


def test_a_filter_on_a_guarded_route_sees_the_controller_a_failing_handler_ran_on() -> None:
    # No stage between the guard and the filter is handed a context, so this is the
    # failure that reaches the filter with only the guard's context built before it.
    seen: dict[str, Any] = {}

    class ObservingGuard(Guard):
        def can_activate(self, context: ExecutionContext) -> bool:
            seen["guard"] = context
            return True

    class ObservingFilter(ExceptionFilter):
        def catch(self, exc: Exception, context: ExecutionContext) -> object:
            seen["filter"] = context
            return None

    @UseFilters(ObservingFilter())
    @UseGuards(ObservingGuard())
    @Controller("/orders", scope=Scope.REQUEST)
    class OrdersController:
        def __init__(self, probe: ResponseProbe) -> None:
            self.probe = probe

        @Get("/")
        async def read(self) -> dict[str, str]:
            seen["controller"] = self
            raise HandlerFailed("the handler failed")

    @Module(controllers=[OrdersController], providers=[ResponseProbe])
    class OrdersModule:
        pass

    [response] = _serve(OrdersModule, "/orders")

    assert response.status_code == 500
    assert seen["guard"].controller is None
    assert seen["filter"] is not seen["guard"]
    assert seen["filter"].controller is seen["controller"]
    assert seen["filter"].response is seen["guard"].response
    assert seen["filter"].response is seen["controller"].probe.response


def test_a_filter_on_a_route_with_no_other_stage_sees_the_stage_the_failure_reached() -> None:
    filtered: list[ExecutionContext] = []
    probes: list[ResponseProbe] = []
    served: list[object] = []

    class ObservingFilter(ExceptionFilter):
        def catch(self, exc: Exception, context: ExecutionContext) -> object:
            filtered.append(context)
            return None

    @UseFilters(ObservingFilter())
    @Controller("/orders", scope=Scope.REQUEST)
    class OrdersController:
        def __init__(self, probe: ResponseProbe, request: HttpRequest) -> None:
            probes.append(probe)
            if "construct" in request.query_params:
                raise HandlerFailed("the constructor failed")

        @Get("/")
        async def read(self) -> dict[str, str]:
            served.append(self)
            raise HandlerFailed("the handler failed")

    @Module(controllers=[OrdersController], providers=[ResponseProbe])
    class OrdersModule:
        pass

    responses = _serve(OrdersModule, "/orders?construct=fail", "/orders")

    assert [response.status_code for response in responses] == [500, 500]
    construction_failure, handler_failure = filtered
    [controller] = served
    assert construction_failure.controller is None
    assert construction_failure.response is probes[0].response
    assert handler_failure.controller is controller
    assert handler_failure.response is probes[1].response
    assert [context.request.path for context in filtered if context.request] == [
        "/orders",
        "/orders",
    ]


def test_a_custom_parameter_sees_the_controller_and_the_response_of_its_request() -> None:
    _PARAMETER_CONTEXTS.clear()
    served: list[Any] = []

    @Controller("/orders", scope=Scope.REQUEST)
    class OrdersController:
        def __init__(self, probe: ResponseProbe) -> None:
            self.probe = probe

        @Get("/")
        async def read(self, value: Annotated[str, Observed]) -> dict[str, str]:
            served.append(self)
            return {"value": value}

    @Module(controllers=[OrdersController], providers=[ResponseProbe])
    class OrdersModule:
        pass

    [response] = _serve(OrdersModule, "/orders")

    [context] = _PARAMETER_CONTEXTS
    [controller] = served
    assert response.json() == {"value": "observed"}
    assert (context.name, context.source) == ("value", "custom")
    assert context.controller is controller
    assert context.response is controller.probe.response
