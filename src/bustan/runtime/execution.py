"""Adapter-neutral HTTP execution planning and runtime orchestration."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from functools import partial
from inspect import iscoroutinefunction
from typing import Any, cast

from anyio import CapacityLimiter, move_on_after, to_thread

from ..common.metadata import ControllerRouteDefinition
from ..common.types import PipelineOverrides
from ..contracts import ApplicationRuntime, HttpRequest, HttpResponse, RouteHandler
from ..kernel.errors import (
    BustanError,
    GuardRejectedError,
    HttpException,
    MethodNotAllowedException,
    NotFoundException,
)
from ..kernel.ioc.container import Container
from ..kernel.ioc.scopes import BoundedInstanceStore
from ..kernel.module.dynamic import ModuleKey
from ..observability.correlation import (
    bind_correlation,
    correlation_from_headers,
    reset_correlation,
)
from ..observability.observability import ObservabilityHooks
from ..pipeline.context import ExecutionContext
from ..pipeline.filters import ExceptionFilter, ProblemDetails, handle_exception
from ..pipeline.guards import run_guards
from ..pipeline.interceptors import call_with_interceptors
from ..pipeline.metadata import PipelineMetadata
from ..pipeline.middleware import Middleware, ResolvedRouteMiddleware
from ..pipeline.pipes import Pipe, run_pipes
from .compiler import (
    GlobalPipelineProvider,
    PipelinePlan,
    PolicyPlan,
    ResponsePlan,
    RouteContract,
)
from .controller_factory import ControllerFactory, PipelineMemo
from .params import (
    BoundParameter,
    HandlerBindingPlan,
    ParameterSource,
    RequestBodyTooLargeError,
    RequestLimits,
    bind_handler_parameters,
    separate_bound_parameters,
)
from .responses import CoercedResponse, ResponseHandler, ResponseSerializer

RuntimeResponse = CoercedResponse
RouteExceptionHandler = Callable[[HttpRequest, Exception], Awaitable[RuntimeResponse]]
_EXCEPTION_RESPONSE_PLAN = ResponsePlan(declared_type=None, default_status_code=200)
_LOGGER = logging.getLogger(__name__)
# The durable partitions cached by the request being decided in this context. A
# refusal undoes its own work and no one else's, and the store is shared between
# every request in flight, so each partition is attributed to whoever cached it
# rather than being inferred from what the store held when the request started.
_CREATED_DURABLE_PARTITIONS: ContextVar[set[object] | None] = ContextVar(
    "bustan_created_durable_partitions", default=None
)
_INTERNAL_SERVER_ERROR_DETAIL = "Internal server error"
# What a response carrying a problem document says it is. A refusal has its own media
# type so that a client can tell a described refusal from whatever else may have written
# the body it received, and every refusal this framework produces carries it.
_PROBLEM_MEDIA_TYPE = "application/problem+json"
# Reserved on the application object for the limits it serves requests under, following
# the framework's convention that a name it owns on someone else's namespace says so.
REQUEST_LIMITS_ATTR = "bustan_request_limits"
# Reserved on the application object for the observability hooks it serves requests
# through, under the same convention as the limits above.
OBSERVABILITY_HOOKS_ATTR = "bustan_observability_hooks"
# Reserved on the application object for the writer that turns its handlers' return
# values into responses, under the same convention as the two above. It holds the
# writer rather than the serializer inside it because the writer is what the request
# path asks for, and building it once when the serializer is declared keeps the promise
# the shared writer below makes: no request builds one to use once.
RESPONSE_HANDLER_ATTR = "bustan_response_handler"


class RequestTimeoutError(BustanError):
    """Raised when one request took longer than the time its application allows it."""


def _problem_response(
    problem: ProblemDetails, headers: Mapping[str, str] | None = None
) -> HttpResponse:
    """Return the response that carries one problem document to the caller.

    A member the document did not set is left out rather than sent as null, because a
    reader of a problem document tells an absent member from one whose value is nothing.
    """

    payload = {key: value for key, value in asdict(problem).items() if value is not None}
    response = HttpResponse.json(payload, status_code=problem.status, headers=headers)
    response.media_type = _PROBLEM_MEDIA_TYPE
    return response


def _refusal_response(error: HttpException, instance: str | None) -> HttpResponse:
    """Return the document one refusal decided before any handler runs answers with.

    A path no route answers, a method a route does not answer and a version nothing
    serves are all turned away before a controller exists, so no pipeline and no
    exception filter stands between the refusal and the caller. Answering each with the
    document *error* describes is what makes one error model cover every refusal rather
    than most of them: a caller reads one shape whichever part of the framework turned
    the request away, and reads it for the errors it meets most often.
    """

    return _problem_response(
        ProblemDetails(
            type=error.problem_type,
            title=error.title,
            status=error.status_code,
            detail=error.detail,
            instance=instance,
            code=error.code,
        ),
        error.headers,
    )


def not_found_response(instance: str | None = None) -> HttpResponse:
    """Return what a caller receives when nothing here answers the path it asked for.

    A transport calls this where its router found no route, and the framework calls it
    where a route exists but serves no version the request named. The two are one answer
    to the caller, who cannot see which of them looked. ``instance`` is the path asked
    for, and appears in the document as the resource the refusal is about.
    """

    return _refusal_response(NotFoundException(), instance)


def method_not_allowed_response(
    instance: str | None = None, allowed: Iterable[str] = ()
) -> HttpResponse:
    """Return what a caller receives for a path that exists but not for this method.

    ``allowed`` names the methods that would have been answered, and reaches the caller
    as the ``Allow`` header a client reads to correct itself. The order is settled here
    rather than left to whichever transport worked the set out, because two transports
    serving one application answer the same caller and an order nobody chose is a
    difference between them that nobody can act on.
    """

    header = {"Allow": ", ".join(sorted(allowed))}
    return _refusal_response(MethodNotAllowedException(headers=header), instance)


class RequestLimitExceptionFilter(ExceptionFilter):
    """Renders the two refusals the runtime's own request limits produce.

    It declares every exception and answers only those two, which is what keeps it out
    of an application's way: the chain ranks a filter that declares a specific type
    ahead of a catch-all one and, among catch-all filters, a later-declared one ahead of
    an earlier, so placing this first means every filter an application installed is
    offered the exception before this is. Answering ``None`` for anything else leaves
    the rest of the chain, and the framework's own fallback, exactly as they were.

    What it returns is the problem-details document the fallback would return, carrying
    the status the limit implies rather than the 500 an unrecognised exception gets.
    """

    exception_types = (Exception,)

    async def catch(self, exc: Exception, context: ExecutionContext) -> HttpResponse | None:
        if isinstance(exc, RequestBodyTooLargeError):
            status_code, title = 413, "Content Too Large"
        elif isinstance(exc, RequestTimeoutError):
            status_code, title = 504, "Gateway Timeout"
        else:
            return None

        _LOGGER.warning("Request refused by a request limit: %s", exc)
        request = context.request
        return _problem_response(
            ProblemDetails(
                type="about:blank",
                title=title,
                status=status_code,
                # A timeout's own message names the budget the deployment configured,
                # which tells a caller how long to hold a connection to exhaust the
                # workers; the status's reason says everything a caller can act on
                # instead.
                detail=str(exc) if status_code < 500 else title,
                instance=request.path if request is not None else None,
            )
        )


_REQUEST_LIMIT_FILTER = RequestLimitExceptionFilter()
# The writer that turns a handler's return value into a response for an application
# that declared no serializer of its own. It reads the plan it is handed and keeps
# nothing of its own between calls, so one writer serves every such request rather than
# each request building one to use once. An application that declares a serializer gets
# its own writer, built once and seated on it; this one is never rebuilt, so what one
# application declares can never become what the next one serves under.
_RESPONSE_HANDLER = ResponseHandler()


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """Compiled runtime plan consumed by HTTP adapters.

    A route is compiled once and served many times, so everything a request would
    otherwise rebuild for itself is built here instead: the three slices of the
    pipeline the runtime resolves at different points, and the memo the components it
    resolves are kept in.
    """

    route_contract: RouteContract
    module_key: ModuleKey
    controller_cls: type[object]
    route_definition: ControllerRouteDefinition
    binding_plan: HandlerBindingPlan
    pipeline_plan: PipelinePlan
    response_plan: ResponsePlan
    policy_plan: PolicyPlan
    is_async_handler: bool
    # What decides whether the request is served at all, and what renders that verdict.
    gate_plan: PipelinePlan = field(init=False, compare=False, repr=False)
    # What the request consumes once it has been admitted.
    remainder_plan: PipelinePlan = field(init=False, compare=False, repr=False)
    # What renders a failure, which is all the error path needs.
    filter_plan: PipelinePlan = field(init=False, compare=False, repr=False)
    # Resolved pipeline components this route may serve every request from. It holds
    # only what cannot come out differently for the next one, so it is a record of how
    # often the container is asked rather than of what it answers.
    pipeline_memo: PipelineMemo = field(
        init=False, compare=False, repr=False, default_factory=PipelineMemo
    )

    def __post_init__(self) -> None:
        plan = self.pipeline_plan
        object.__setattr__(
            self, "gate_plan", PipelinePlan(guards=plan.guards, filters=plan.filters)
        )
        object.__setattr__(
            self,
            "remainder_plan",
            PipelinePlan(pipes=plan.pipes, interceptors=plan.interceptors),
        )
        object.__setattr__(self, "filter_plan", PipelinePlan(filters=plan.filters))

    @property
    def handler_name(self) -> str:
        return self.route_definition.handler_name

    @property
    def method(self) -> str:
        return self.route_contract.method

    @property
    def path(self) -> str:
        return self.route_contract.path


@dataclass(frozen=True, slots=True)
class HttpExecutionResult:
    """Result produced by the adapter-neutral HTTP execution engine."""

    response: RuntimeResponse
    context: ExecutionContext | None
    error: Exception | None = None


def compile_execution_plan(route_contract: RouteContract) -> ExecutionPlan:
    """Compile a route contract into its runtime execution plan."""

    return ExecutionPlan(
        route_contract=route_contract,
        module_key=route_contract.module_key,
        controller_cls=route_contract.controller_cls,
        route_definition=route_contract.route_definition,
        binding_plan=route_contract.binding_plan,
        pipeline_plan=route_contract.pipeline_plan,
        response_plan=route_contract.response_plan,
        policy_plan=route_contract.policy_plan,
        is_async_handler=iscoroutinefunction(route_contract.route_definition.handler),
    )


def compile_execution_plans(
    route_contracts: tuple[RouteContract, ...],
) -> tuple[ExecutionPlan, ...]:
    """Compile stable execution plans for all discovered route contracts."""

    return tuple(compile_execution_plan(route_contract) for route_contract in route_contracts)


def create_route_handler(
    container: Container,
    execution_plan: ExecutionPlan,
    middleware_chain: tuple[ResolvedRouteMiddleware, ...] = (),
    pipeline_override_registry: PipelineOverrides[PipelineMetadata] | None = None,
) -> RouteHandler:
    """Build the framework's entry point for one compiled route.

    The returned handler is what a transport adapter calls once it has converted a
    request, and it owns the whole request: the scopes are pushed before the first
    middleware runs and released only after the last one has returned. That is what
    lets a middleware resolving a request-scoped provider after ``call_next`` see the
    instance the handler saw, rather than a second one built once the scope had
    already closed underneath it.
    """

    factory = ControllerFactory(
        container,
        pipeline_override_registry=pipeline_override_registry,
    )

    async def run_route(request: HttpRequest) -> RuntimeResponse:
        result = await execute_http_route(
            application_runtime=request.app,
            container=container,
            factory=factory,
            execution_plan=execution_plan,
            request=request,
        )
        return result.response

    async def render_error(request: HttpRequest, error: Exception) -> RuntimeResponse:
        result = await execute_http_exception(
            application_runtime=request.app,
            container=container,
            factory=factory,
            execution_plan=execution_plan,
            request=request,
            error=error,
        )
        return result.response

    async def handle(request: HttpRequest) -> RuntimeResponse:
        # The request is named before anything runs for it, and the name is bound for
        # as long as the request is, so every log record and every span it produces
        # carries the same correlation id - including the ones a middleware writes
        # before the route is reached and the ones a failure writes after it is left.
        correlation_token = bind_correlation(correlation_from_headers(request.headers))
        request_token = container.scope_manager.push_request(request)
        application_token = container.scope_manager.push_application(
            _application_runtime(request.app)
        )
        try:
            return await run_middleware_chain(
                request,
                middleware_chain,
                factory,
                run_route,
                exception_handler=render_error,
            )
        finally:
            # The request is over only once the outermost middleware has returned, so
            # what was scoped to it is released here rather than inside the route.
            container.scope_manager.clear_request_state(request)
            container.scope_manager.pop_application(application_token)
            container.scope_manager.pop_request(request_token)
            reset_correlation(correlation_token)

    return handle


async def run_middleware_chain(
    request: HttpRequest,
    middleware_chain: tuple[ResolvedRouteMiddleware, ...],
    factory: ControllerFactory,
    terminal_handler: RouteHandler,
    *,
    exception_handler: RouteExceptionHandler | None = None,
) -> RuntimeResponse:
    """Run the route's middleware chain, ending in *terminal_handler*."""

    async def invoke(index: int, current_request: HttpRequest) -> RuntimeResponse:
        try:
            if index >= len(middleware_chain):
                return cast(RuntimeResponse, await terminal_handler(current_request))

            entry = middleware_chain[index]

            async def call_next(next_request: HttpRequest) -> RuntimeResponse:
                return await invoke(index + 1, next_request)

            middleware_ref = entry.middleware
            if isinstance(middleware_ref, type | Middleware):
                middleware = factory.resolve_components(
                    (middleware_ref,),
                    Middleware,
                    module=entry.declaring_module,
                    request=current_request,
                    kind="middleware",
                )[0]
                return cast(RuntimeResponse, await middleware.use(current_request, call_next))

            result = cast(Any, middleware_ref)(current_request, call_next)
            if inspect.isawaitable(result):
                return cast(RuntimeResponse, await cast(Any, result))
            return cast(RuntimeResponse, result)
        except Exception as exc:
            if exception_handler is None:
                raise
            return await exception_handler(current_request, exc)

    return await invoke(0, request)


async def execute_http_route(
    *,
    application_runtime: object,
    container: Container,
    factory: ControllerFactory,
    execution_plan: ExecutionPlan,
    request: HttpRequest,
) -> HttpExecutionResult:
    """Execute one compiled HTTP route through the shared runtime pipeline."""

    # The request is bound for the whole execution, not merely for the duration of one
    # resolve call, so anything running inside the route - a handler, a guard, an
    # interceptor - can reach the request being served and the providers scoped to it.
    request_token = container.scope_manager.push_request(request)
    application_token = container.scope_manager.push_application(
        _application_runtime(application_runtime)
    )
    response_context = HttpResponse()
    response_token = container.scope_manager.push_response(response_context)
    observability = observability_hooks_of(application_runtime)
    limits = request_limits_of(application_runtime)
    response_handler = response_handler_of(application_runtime)
    context: ExecutionContext | None = None
    filters: tuple[ExceptionFilter, ...] | None = None
    observation = None
    created_durable_partitions: set[object] | None = None

    try:
        # The clock covers the whole of the request the application pays for, not
        # only the handler: a guard that hangs, a provider that never resolves and a
        # body that never finishes arriving each hold a worker exactly as a slow
        # handler does. Rendering the refusal happens outside the scope, so the
        # filters that answer a timeout are not themselves running out of time.
        with move_on_after(limits.timeout_seconds):
            # The context and the observation come first, before anything a request pays
            # for can fail. An exception raised while a constructor runs then has the same
            # context, the same filter chain and the same metrics as one raised inside the
            # handler, instead of leaving the route with nothing to answer it with.
            context = _http_context(
                execution_plan,
                request=request,
                response_context=response_context,
                container=container,
                controller=None,
            )
            observation = observability.start_request(context)

            # Guards decide whether the request is served at all, so they and the filters
            # that render their verdict are the only components resolved before that
            # decision. Everything the request would consume once it is admitted - the
            # controller, whatever it injects, the pipes and the interceptors - is built
            # after, so a refused caller pays for none of it and leaves nothing behind.
            with _durable_partitions_created(container, execution_plan) as created:
                created_durable_partitions = created
                gate = await factory.resolve_pipeline_async(
                    execution_plan.gate_plan,
                    module=execution_plan.module_key,
                    request=request,
                    memo=execution_plan.pipeline_memo,
                )
                filters = gate.filters

                await run_guards(context, gate.guards)
            # The request was admitted, so anything cached from here on is work it asked
            # for and is not undone if a later stage fails.
            created_durable_partitions = None

            controller_instance = await factory.instantiate_async(
                execution_plan.controller_cls,
                module=execution_plan.module_key,
                request=request,
            )
            handler = getattr(controller_instance, execution_plan.handler_name)
            # The controller exists only now, so the context every later stage sees is
            # rebuilt around it; guards saw the one that could not name an instance yet.
            context = _http_context(
                execution_plan,
                request=request,
                response_context=response_context,
                container=container,
                controller=controller_instance,
            )

            remainder = await factory.resolve_pipeline_async(
                execution_plan.remainder_plan,
                module=execution_plan.module_key,
                request=request,
                memo=execution_plan.pipeline_memo,
            )

            bound_parameters = await bind_handler_parameters(
                request,
                execution_plan.binding_plan,
                context,
                limits,
            )
            piped_parameters = await _apply_pipes(
                bound_parameters,
                context,
                remainder.pipes,
                execution_plan.binding_plan,
            )
            positional_arguments, keyword_arguments = separate_bound_parameters(piped_parameters)

            async def final_handler() -> object:
                if execution_plan.is_async_handler:
                    return await handler(*positional_arguments, **keyword_arguments)
                return await to_thread.run_sync(
                    partial(handler, *positional_arguments, **keyword_arguments),
                    limiter=_sync_handler_limiter(limits),
                )

            result = await call_with_interceptors(
                context,
                remainder.interceptors,
                final_handler,
            )
            response = response_handler.write(
                result=result, response_plan=execution_plan.response_plan
            )
            response = _merge_response_context(
                response_context,
                response,
                default_status_code=execution_plan.response_plan.default_status_code,
            )
            _apply_rate_limit_headers(request, response)

            if observation is not None:
                observability.finish_request(
                    observation,
                    status_code=_response_status_code(response),
                )
            return HttpExecutionResult(response=response, context=context)

        # The block above ends in a return, so arriving here means the deadline
        # passed and the scope swallowed the cancellation on its way out.
        raise RequestTimeoutError(f"The request exceeded the {limits.timeout_seconds} second limit")
    except Exception as exc:
        if isinstance(exc, GuardRejectedError):
            _evict_durable_partitions(container, created_durable_partitions)
        response = await _render_failure(
            exc,
            context=context,
            filters=filters,
            factory=factory,
            execution_plan=execution_plan,
            response_context=response_context,
            request=request,
            response_handler=response_handler,
        )
        if observation is not None:
            observability.finish_request(
                observation,
                status_code=_response_status_code(response),
                error=exc,
            )
        return HttpExecutionResult(response=response, context=context, error=exc)
    finally:
        container.scope_manager.pop_response(response_token)
        container.scope_manager.pop_application(application_token)
        container.scope_manager.pop_request(request_token)


async def execute_http_exception(
    *,
    application_runtime: object,
    container: Container,
    factory: ControllerFactory,
    execution_plan: ExecutionPlan,
    request: HttpRequest,
    error: Exception,
) -> HttpExecutionResult:
    """Render an exception through the route's compiled filter chain.

    A failure while assembling that chain is rendered exactly as the main path renders
    one, so a request that failed in a middleware is answered with the same document,
    in the same content type, as one that failed inside its handler, and a resolution
    failure never reaches the caller as a traceback.

    The route never ran, so nothing it would have consumed is built here: rendering an
    error needs the context and the filters and nothing else. A controller whose
    constructor raises therefore cannot turn the exception the caller is owed an answer
    to into a second failure that hides it.
    """

    request_token = container.scope_manager.push_request(request)
    application_token = container.scope_manager.push_application(
        _application_runtime(application_runtime)
    )
    response_context = HttpResponse()
    response_token = container.scope_manager.push_response(response_context)
    observability = observability_hooks_of(application_runtime)
    response_handler = response_handler_of(application_runtime)
    observation = None
    context: ExecutionContext | None = None
    filters: tuple[ExceptionFilter, ...] | None = None

    try:
        # The context comes first, before anything that can fail while it is built, so
        # the filters have something to answer with whatever else goes wrong. It names
        # no controller because none was constructed for this request.
        context = _http_context(
            execution_plan,
            request=request,
            response_context=response_context,
            container=container,
            controller=None,
        )
        resolved_pipeline = await factory.resolve_pipeline_async(
            execution_plan.filter_plan,
            module=execution_plan.module_key,
            request=request,
            memo=execution_plan.pipeline_memo,
        )
        filters = resolved_pipeline.filters
        observation = observability.start_request(context)
        filtered_result = await handle_exception(context, error, _with_limit_filter(filters))
        response = response_handler.write(
            result=filtered_result,
            response_plan=_EXCEPTION_RESPONSE_PLAN,
        )
        response = _merge_response_context(
            response_context,
            response,
            default_status_code=_EXCEPTION_RESPONSE_PLAN.default_status_code,
        )
        _apply_rate_limit_headers(request, response)
        observability.finish_request(
            observation,
            status_code=_response_status_code(response),
            error=error,
        )
        return HttpExecutionResult(response=response, context=context, error=error)
    except Exception as exc:
        response = await _render_failure(
            exc,
            context=context,
            filters=filters,
            factory=factory,
            execution_plan=execution_plan,
            response_context=response_context,
            request=request,
            response_handler=response_handler,
        )
        if observation is not None:
            observability.finish_request(
                observation,
                status_code=_response_status_code(response),
                error=exc,
            )
        return HttpExecutionResult(response=response, context=context, error=error)
    finally:
        container.scope_manager.pop_response(response_token)
        container.scope_manager.pop_application(application_token)
        container.scope_manager.pop_request(request_token)


async def _render_failure(
    exc: Exception,
    *,
    context: ExecutionContext | None,
    filters: tuple[ExceptionFilter, ...] | None,
    factory: ControllerFactory,
    execution_plan: ExecutionPlan,
    response_context: HttpResponse,
    request: HttpRequest,
    response_handler: ResponseHandler,
) -> RuntimeResponse:
    """Turn an exception the route could not handle itself into a client response.

    A context is what an exception filter needs to run, so once there is one the
    exception is given to filters whatever else failed. The route's own filters are
    used when they were resolved; when the failure was in resolving them, the
    application-wide chain is resolved on its own and used instead, and even an empty
    chain still ends in the framework's problem-details mapping rather than a fixed
    status. Only a failure that leaves no context at all is answered with an opaque
    500, logged where an operator can read it and saying nothing about the internals.

    ``response_handler`` is the writer the application being served declared. It is
    passed in rather than looked up because the caller resolved it for this request
    already, and an error path is the last place that should serialize through a
    different writer than the success path beside it.
    """

    if context is not None:
        if filters is None:
            filters = await _global_filters(factory, execution_plan, request)
        filtered_result = await handle_exception(context, exc, _with_limit_filter(filters))
        response = response_handler.write(
            result=filtered_result,
            response_plan=_EXCEPTION_RESPONSE_PLAN,
        )
    else:
        _LOGGER.exception("Unhandled exception during request setup", exc_info=exc)
        response = HttpResponse.json({"detail": _INTERNAL_SERVER_ERROR_DETAIL}, status_code=500)

    response = _merge_response_context(
        response_context,
        response,
        default_status_code=_EXCEPTION_RESPONSE_PLAN.default_status_code,
    )
    _apply_rate_limit_headers(request, response)
    return response


def _http_context(
    execution_plan: ExecutionPlan,
    *,
    request: HttpRequest,
    response_context: HttpResponse,
    container: Container,
    controller: object,
) -> ExecutionContext:
    """Build the execution context for one request at the stage it has reached.

    ``controller`` is ``None`` until the controller has been constructed, which is
    after the guards have admitted the request. Everything else the context carries is
    known from the compiled plan, so a guard and a filter running before any instance
    exists still see the route, the handler, the declared class and the policy plan.
    """

    return ExecutionContext.create_http(
        request=request,
        response=response_context,
        handler=execution_plan.route_definition.handler,
        controller_cls=execution_plan.controller_cls,
        module=execution_plan.module_key,
        controller=controller,
        container=container,
        route=execution_plan.route_definition,
        route_contract=execution_plan.route_contract,
        policy_plan=execution_plan.policy_plan,
    )


async def _global_filters(
    factory: ControllerFactory,
    execution_plan: ExecutionPlan,
    request: HttpRequest,
) -> tuple[ExceptionFilter, ...]:
    """Resolve the application-wide filter chain declared for this route.

    This runs only after resolving the route's own chain has already failed, so it
    resolves the globally declared filters alone and answers with an empty chain if
    even those cannot be built. Reporting that second failure in place of the first
    would hide the exception the caller is owed an answer to.
    """

    global_filters = tuple(
        component
        for component in execution_plan.pipeline_plan.filters
        if isinstance(component, GlobalPipelineProvider)
    )
    if not global_filters:
        return ()

    try:
        resolved = await factory.resolve_pipeline_async(
            PipelinePlan(filters=global_filters),
            module=execution_plan.module_key,
            request=request,
            memo=execution_plan.pipeline_memo,
        )
    except Exception:
        _LOGGER.exception("Could not resolve the application-wide exception filters")
        return ()
    return resolved.filters


class _AttributedDurableStore(BoundedInstanceStore):
    """A durable store that tells the request being decided which partitions it cached.

    A write is reported whether it added a partition or replaced one, because the
    instance the store held under that key is gone either way. Nothing is reported
    when no request is being decided in the writer's context, which is every request
    already admitted and every route that declares no guard.
    """

    __slots__ = ()

    def __setitem__(self, key: Any, instance: object) -> None:
        created = _CREATED_DURABLE_PARTITIONS.get()
        if created is not None:
            created.add(key)
        super().__setitem__(key, instance)


def _attribute_durable_writes(container: Container) -> None:
    """Make a container's durable store report every partition it caches.

    The store is left in place and its class rebound, rather than a reporting store
    being put in the container's stead: every resolution already holds this object,
    so an exchange would lose whatever a request in flight wrote to the old one.
    """

    store = container.scope_manager.durable_instances
    if type(store) is not _AttributedDurableStore:
        store.__class__ = _AttributedDurableStore


@contextmanager
def _durable_partitions_created(
    container: Container,
    execution_plan: ExecutionPlan,
) -> Iterator[set[object] | None]:
    """Collect the durable partitions a route that can refuse creates while deciding.

    Only a guard refuses a request, so a route that declares none can leave nothing
    behind to undo and is not made to record anything.
    """

    if not execution_plan.pipeline_plan.guards:
        yield None
        return

    _attribute_durable_writes(container)
    created: set[object] = set()
    token = _CREATED_DURABLE_PARTITIONS.set(created)
    try:
        yield created
    finally:
        _CREATED_DURABLE_PARTITIONS.reset(token)


def _evict_durable_partitions(
    container: Container,
    created: set[object] | None,
) -> None:
    """Drop the durable partitions a refused request created while it was decided.

    A durable instance is cached under a key derived from the request, so a caller the
    application then refuses would otherwise decide what the cache holds: it names a
    partition, the partition is built and kept, and a bounded store fills with entries
    no admitted caller asked for.

    What goes is what this request cached and nothing else. The store is shared, so a
    partition that appeared while this request was being decided but was cached by
    another one stays: it is that request's work, and that request is being served.
    """

    if not created:
        return

    durable_instances = container.scope_manager.durable_instances
    for key in created:
        durable_instances.pop(key, None)


def _with_limit_filter(filters: tuple[ExceptionFilter, ...]) -> tuple[ExceptionFilter, ...]:
    """Put the runtime's own limit filter behind every filter the application declared.

    First in the tuple is last in preference, because the chain prefers a filter that
    was declared later over one declared earlier when both catch the same breadth. An
    application therefore always gets to answer its own timeouts and oversized bodies,
    and this is what answers them when it does not.
    """

    return (_REQUEST_LIMIT_FILTER, *filters)


def set_request_limits(application_runtime: object, limits: RequestLimits) -> None:
    """Declare the limits *application_runtime* serves its requests under.

    The limits belong to an application rather than to the process, so two applications
    in one process do not have to agree on how large a body or how long a request one
    of them accepts. Whatever is not declared this way is served under the defaults,
    which are finite; there is no way to end up with no limits by omission.
    """

    setattr(_application_runtime(application_runtime), REQUEST_LIMITS_ATTR, limits)


def request_limits_of(application_runtime: object) -> RequestLimits:
    """Return the limits *application_runtime* serves its requests under."""

    limits = getattr(_application_runtime(application_runtime), REQUEST_LIMITS_ATTR, None)
    return limits if isinstance(limits, RequestLimits) else RequestLimits()


def set_observability_hooks(application_runtime: object, hooks: ObservabilityHooks) -> None:
    """Declare the hooks *application_runtime* serves its requests through.

    The hooks belong to an application rather than to the process, so two applications
    in one process can report to two different backends, and neither has to agree with
    the other about which one that is. An application that declares none is served
    through hooks that record nothing.
    """

    setattr(_application_runtime(application_runtime), OBSERVABILITY_HOOKS_ATTR, hooks)


def observability_hooks_of(application_runtime: object) -> ObservabilityHooks:
    """Return the hooks *application_runtime* serves its requests through."""

    hooks = getattr(_application_runtime(application_runtime), OBSERVABILITY_HOOKS_ATTR, None)
    return ObservabilityHooks.resolve(hooks if isinstance(hooks, ObservabilityHooks) else None)


def set_response_serializer(application_runtime: object, serializer: ResponseSerializer) -> None:
    """Declare the serializer *application_runtime* writes its responses through.

    The serializer belongs to an application rather than to the process, so two
    applications in one process can render the same handler return value two different
    ways, and neither has to agree with the other about which one that is. An
    application that declares none writes through the framework's default serializer,
    so there is no way to end up with nothing to serialize with.

    The writer that reads the compiled response plan is built here, once, and seated on
    the application; the serializer only decides what a plan that asks for serialization
    produces, and the raw, stream and file strategies are unaffected either way.
    """

    setattr(
        _application_runtime(application_runtime),
        RESPONSE_HANDLER_ATTR,
        ResponseHandler(serializer),
    )


def response_handler_of(application_runtime: object) -> ResponseHandler:
    """Return the writer that turns *application_runtime*'s return values into responses."""

    handler = getattr(_application_runtime(application_runtime), RESPONSE_HANDLER_ATTR, None)
    return handler if isinstance(handler, ResponseHandler) else _RESPONSE_HANDLER


def _sync_handler_limiter(limits: RequestLimits) -> CapacityLimiter:
    """Return the limiter that bounds how many synchronous handlers run at once.

    This is the running loop's own default thread limiter rather than a second one
    beside it. A synchronous handler is offloaded to a thread, and so is everything
    else in the process that offloads work the same way; a private limiter would bound
    the handlers while the total number of threads stayed whatever the two limiters
    happened to add up to, which is not a ceiling anyone set.

    It follows that this one bound is per event loop where the rest are per application:
    two applications serving on one loop share it, and the last of them to serve a
    request is the one whose figure stands. A deployment that wants two different thread
    ceilings needs two loops to hold them.
    """

    limiter = to_thread.current_default_thread_limiter()
    if limiter.total_tokens != limits.sync_handler_threads:
        limiter.total_tokens = limits.sync_handler_threads
    return limiter


def _application_runtime(application_runtime: object) -> object:
    """Return the Bustan application behind whatever the transport handed over.

    ``APPLICATION`` names the application a provider is running inside, and that has
    to be the same object whichever way the resolution was entered. An adapter that
    passes its own server instance is unwrapped to the runtime attached to it, so a
    provider is never handed the web server on one path and the application on another.

    An application is recognised by the shape :class:`ApplicationRuntime` declares
    rather than by its class, because the class is assembled a layer above this one.
    Anything that is neither an application nor a server carrying one is handed back
    untouched, so a transport the framework does not recognise is passed through as
    itself rather than being reported as an application it is not.
    """

    if isinstance(application_runtime, ApplicationRuntime):
        return application_runtime
    state = getattr(application_runtime, "state", None)
    attached = getattr(state, "bustan_application", None)
    if isinstance(attached, ApplicationRuntime):
        return attached
    return application_runtime


async def _apply_pipes(
    bound_parameters: tuple[BoundParameter, ...],
    context: ExecutionContext,
    pipes: tuple[Pipe, ...],
    binding_plan: HandlerBindingPlan,
) -> tuple[BoundParameter, ...]:
    if not pipes and binding_plan.validation_mode.value != "auto":
        return bound_parameters

    transformed_parameters: list[BoundParameter] = []
    for bound_parameter in bound_parameters:
        if bound_parameter.binding.source is ParameterSource.REQUEST:
            transformed_parameters.append(bound_parameter)
            continue

        transformed_value = await run_pipes(
            bound_parameter.value,
            context.with_parameter(
                name=bound_parameter.binding.name,
                source=bound_parameter.binding.source.value,
                annotation=bound_parameter.binding.annotation,
                value=bound_parameter.value,
                validation_mode=binding_plan.validation_mode.value,
                validate_custom_decorators=binding_plan.validate_custom_decorators,
            ),
            pipes,
        )
        transformed_parameters.append(
            BoundParameter(binding=bound_parameter.binding, value=transformed_value)
        )

    return tuple(transformed_parameters)


def _apply_rate_limit_headers(request: HttpRequest, response: RuntimeResponse) -> None:
    rate_limit = request.slots.rate_limit
    if rate_limit is None:
        return

    response.headers["X-RateLimit-Limit"] = str(rate_limit.limit)
    response.headers["X-RateLimit-Remaining"] = str(rate_limit.remaining)
    response.headers["X-RateLimit-Reset"] = str(rate_limit.reset)


def _response_status_code(response: RuntimeResponse) -> int:
    return int(response.status_code)


def _merge_response_context(
    response_context: HttpResponse,
    response: RuntimeResponse,
    *,
    default_status_code: int,
) -> RuntimeResponse:
    for header_name, header_value in response_context.headers.items():
        response.headers[header_name] = header_value

    if response_context.status_code != 200 and response.status_code in {
        200,
        default_status_code,
    }:
        response.status_code = response_context.status_code

    return response


__all__ = [
    "OBSERVABILITY_HOOKS_ATTR",
    "REQUEST_LIMITS_ATTR",
    "RESPONSE_HANDLER_ATTR",
    "ExecutionPlan",
    "HttpExecutionResult",
    "RequestLimitExceptionFilter",
    "RequestTimeoutError",
    "RouteExceptionHandler",
    "RuntimeResponse",
    "compile_execution_plan",
    "compile_execution_plans",
    "create_route_handler",
    "execute_http_exception",
    "execute_http_route",
    "method_not_allowed_response",
    "not_found_response",
    "observability_hooks_of",
    "request_limits_of",
    "response_handler_of",
    "run_middleware_chain",
    "set_observability_hooks",
    "set_request_limits",
    "set_response_serializer",
]
