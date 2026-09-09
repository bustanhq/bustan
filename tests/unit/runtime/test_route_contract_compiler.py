"""Unit tests for compiled route contracts."""

from __future__ import annotations

import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import fields
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec
from types import ModuleType
from typing import cast

import pytest
from starlette.responses import Response

from bustan import (
    APP_GUARD,
    APP_INTERCEPTOR,
    APP_PIPE,
    ClassProvider,
    Controller,
    ExecutionContext,
    ExistingProvider,
    FactoryProvider,
    Get,
    HttpResponse,
    Interceptor,
    Module,
    UseFilters,
    UseGuards,
    UseInterceptors,
    UsePipes,
    ValueProvider,
)
from bustan.common.types import Provider
from bustan.kernel.errors import RouteDefinitionError
from bustan.kernel.ioc.container import build_container
from bustan.kernel.module.graph import build_module_graph
from bustan.pipeline.interceptors import CallHandler
from bustan.runtime.compiler import (
    GlobalPipelineProvider,
    ResponsePlan,
    ResponseStrategy,
    RouteCompiler,
    RouteContract,
    compile_route_contracts,
)


class _BodyRewritingInterceptor(Interceptor):
    """A global interceptor that declares it rewrites the body of the response."""

    mutates_response_body = True

    async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
        raise NotImplementedError


class _PassThroughInterceptor(Interceptor):
    """A global interceptor that declares nothing about the response body."""

    async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
        raise NotImplementedError


@Controller("/raw")
class _RawController:
    @Get("/")
    def index(self) -> HttpResponse:
        return HttpResponse.json({"status": "ok"})


@Controller("/plain")
class _StandardController:
    @Get("/")
    def index(self) -> dict[str, str]:
        return {"status": "ok"}


def _return_the_interceptor(interceptor: object) -> object:
    """Build a global interceptor out of one the container already knows how to build."""

    return interceptor


def _compile_routes(
    controller: type[object], providers: list[Provider]
) -> tuple[RouteContract, ...]:
    """Compile one controller's routes under the given global pipeline declarations."""

    @Module(controllers=[controller], providers=providers)
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)
    return compile_route_contracts(graph, container)


# The same two global interceptors, written every way a module may write them. The last
# two spell the components out one at a time, which the module compiler folds into a
# single binding that builds them together.
_AS_A_LIST: list[Provider] = [
    ValueProvider(
        provide=APP_INTERCEPTOR, use_value=[_PassThroughInterceptor(), _BodyRewritingInterceptor()]
    )
]
_AS_ONE_ENTRY: list[Provider] = [
    ClassProvider(provide=APP_INTERCEPTOR, use_class=_BodyRewritingInterceptor)
]
_AS_TWO_ENTRIES: list[Provider] = [
    ClassProvider(provide=APP_INTERCEPTOR, use_class=_PassThroughInterceptor),
    ClassProvider(provide=APP_INTERCEPTOR, use_class=_BodyRewritingInterceptor),
]
_AS_TWO_MIXED_ENTRIES: list[Provider] = [
    ClassProvider(provide=APP_INTERCEPTOR, use_class=_PassThroughInterceptor),
    ValueProvider(provide=APP_INTERCEPTOR, use_value=_BodyRewritingInterceptor()),
]


def test_route_contracts_include_route_identity_and_ownership() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/{user_id}")
        def read_user(self, user_id: int) -> dict[str, int]:
            return {"user_id": user_id}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    [contract] = compile_route_contracts(graph, container)

    assert contract.module_key is AppModule
    assert contract.controller_cls is UsersController
    assert contract.handler_name == "read_user"
    assert contract.method == "GET"
    assert contract.path == "/users/{user_id}"
    assert contract.name == "read_user"


def test_route_contracts_attach_companion_plans_once_in_stable_order() -> None:
    global_guard = object()
    global_pipe = object()
    controller_guard = object()
    handler_guard = object()
    controller_interceptor = object()
    handler_pipe = object()
    handler_filter = object()

    @UseGuards(controller_guard)
    @UseInterceptors(controller_interceptor)
    @Controller("/users")
    class UsersController:
        @UseGuards(handler_guard)
        @UsePipes(handler_pipe)
        @UseFilters(handler_filter)
        @Get("/{user_id}")
        def read_user(self, user_id: int) -> dict[str, int]:
            return {"user_id": user_id}

    @Module(
        controllers=[UsersController],
        providers=[
            ValueProvider(provide=APP_GUARD, use_value=global_guard),
            ValueProvider(provide=APP_PIPE, use_value=global_pipe),
        ],
    )
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    [contract] = RouteCompiler(graph, container).compile()

    assert contract.binding_plan.handler_name == "read_user"
    assert [binding.name for binding in contract.binding_plan.parameters] == ["user_id"]
    # A global component is carried as the reference the runtime resolves per request,
    # ahead of everything the controller and the handler declared.
    assert contract.pipeline_plan.guards == (
        GlobalPipelineProvider(APP_GUARD, AppModule, global_guard),
        controller_guard,
        handler_guard,
    )
    assert contract.pipeline_plan.pipes == (
        GlobalPipelineProvider(APP_PIPE, AppModule, global_pipe),
        handler_pipe,
    )
    assert contract.pipeline_plan.interceptors == (controller_interceptor,)
    assert contract.pipeline_plan.filters == (handler_filter,)
    assert contract.response_plan is not None
    assert contract.policy_plan.auth is None
    assert contract.policy_plan.roles == ()
    assert contract.policy_plan.permissions == ()


def test_route_contracts_normalize_versions_and_hosts() -> None:
    @Controller("/users", version="1", host="api.example.test")
    class UsersController:
        @Get("/", version=["2", "3"])
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    [contract] = compile_route_contracts(graph, container)

    assert contract.versions == ("2", "3")
    assert contract.hosts == ("api.example.test",)


def test_route_contracts_allow_route_hosts_to_override_controller_hosts() -> None:
    @Controller("/users", hosts=("api.example.test", "admin.example.test"))
    class UsersController:
        @Get("/", hosts=("edge.example.test", "api.example.test"))
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    [contract] = compile_route_contracts(graph, container)

    assert contract.hosts == ("edge.example.test", "api.example.test")


def test_route_contracts_resolve_stringified_return_annotations_for_response_strategies() -> None:
    @Controller("/users")
    class UsersController:
        @Get("/")
        def index(self) -> HttpResponse:
            return HttpResponse.json({"status": "ok"})

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    [contract] = compile_route_contracts(graph, container)

    assert contract.response_plan.strategy is ResponseStrategy.RAW


class _RefuseWebServerImports(MetaPathFinder):
    """Import finder that answers for a package as the interpreter would if it were absent."""

    def __init__(self, package: str) -> None:
        self._package = package

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None = None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        if fullname.partition(".")[0] == self._package:
            raise ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)
        return None


@contextmanager
def _package_uninstalled(package: str) -> Iterator[None]:
    """Run a block as if a package were not installed in the environment at all.

    The suite runs with every optional web server present, so a path that only works
    because one of them is importable cannot be told from a path that does not need one
    unless the absence is staged. Both halves of the absence are staged here: an already
    imported module is taken back out of the module table, and a fresh import of one
    raises the error a missing distribution raises.
    """

    hidden = {
        name: module for name, module in sys.modules.items() if name.partition(".")[0] == package
    }
    for name in hidden:
        del sys.modules[name]

    finder = _RefuseWebServerImports(package)
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        sys.meta_path.remove(finder)
        sys.modules.update(hidden)


def test_routes_compile_with_no_web_server_installed() -> None:
    """A route compiles in an install that named no web server extra.

    Compiling a route is on the startup path of every application, including one served
    by an adapter the framework does not ship, so it may not need any particular web
    server to be importable.
    """

    @Controller("/health")
    class HealthController:
        @Get("/")
        def read(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[HealthController])
    class AppModule:
        pass

    with _package_uninstalled("starlette"):
        graph = build_module_graph(AppModule)
        container = build_container(graph)

        [contract] = compile_route_contracts(graph, container)

    assert contract.full_path == "/health"
    assert contract.response_plan.strategy is ResponseStrategy.STANDARD


def test_a_route_declaring_a_web_server_response_type_compiles_to_the_raw_strategy() -> None:
    """A declared transport response is still recognised where that transport is present."""

    @Controller("/reports")
    class ReportsController:
        @Get("/")
        def download(self) -> Response:
            return Response(b"report", media_type="text/plain")

    @Module(controllers=[ReportsController])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    [contract] = compile_route_contracts(graph, container)

    assert contract.response_plan.declared_type is Response
    assert contract.response_plan.strategy is ResponseStrategy.RAW


def test_global_pipeline_components_are_named_rather_than_built_while_routes_compile() -> None:
    built: list[str] = []

    class CountingGuard:
        def __init__(self) -> None:
            built.append("guard")

    @Controller("/users")
    class UsersController:
        @Get("/")
        def index(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(
        controllers=[UsersController],
        providers=[ClassProvider(provide=APP_GUARD, use_class=CountingGuard)],
    )
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    [contract] = compile_route_contracts(graph, container)

    assert built == []
    assert contract.pipeline_plan.guards == (
        GlobalPipelineProvider(APP_GUARD, AppModule, CountingGuard),
    )
    global_guard = cast(GlobalPipelineProvider, contract.pipeline_plan.guards[0])
    assert global_guard.label == "CountingGuard"


def test_a_body_mutating_global_interceptor_declared_as_a_list_is_refused_on_a_raw_route() -> None:
    with pytest.raises(RouteDefinitionError, match="_BodyRewritingInterceptor"):
        _compile_routes(_RawController, _AS_A_LIST)


def test_a_body_mutating_global_interceptor_declared_as_one_entry_is_refused_on_a_raw_route() -> (
    None
):
    with pytest.raises(RouteDefinitionError, match="_BodyRewritingInterceptor"):
        _compile_routes(_RawController, _AS_ONE_ENTRY)


def test_a_body_mutating_global_interceptor_declared_as_two_entries_is_refused_on_a_raw_route() -> (
    None
):
    """A module may declare each global interceptor as its own entry rather than as a list.

    Those declarations are joined into one binding that builds them together, and the
    binding names none of them, so the refusal has to read the declarations the join was
    made from or it sees an empty slot where the module declared two components.
    """

    with pytest.raises(RouteDefinitionError) as as_two_entries:
        _compile_routes(_RawController, _AS_TWO_ENTRIES)

    with pytest.raises(RouteDefinitionError) as as_a_list:
        _compile_routes(_RawController, _AS_A_LIST)

    assert "_BodyRewritingInterceptor" in str(as_two_entries.value)
    assert str(as_two_entries.value) == str(as_a_list.value)


def test_a_folded_declaration_mixing_a_class_and_a_value_is_refused_on_a_raw_route() -> None:
    """Every declaration in a joined binding is read, whichever way each one was written."""

    with pytest.raises(RouteDefinitionError, match="_BodyRewritingInterceptor"):
        _compile_routes(_RawController, _AS_TWO_MIXED_ENTRIES)


def test_a_folded_declaration_beside_a_factory_still_reads_the_declarations_it_can() -> None:
    """A joined entry naming no component leaves the entries beside it readable."""

    with pytest.raises(RouteDefinitionError, match="_BodyRewritingInterceptor"):
        _compile_routes(
            _RawController,
            [
                FactoryProvider(provide=APP_INTERCEPTOR, use_factory=_PassThroughInterceptor),
                ClassProvider(provide=APP_INTERCEPTOR, use_class=_BodyRewritingInterceptor),
            ],
        )


def test_two_declarations_of_one_global_token_read_back_as_the_components_they_named() -> None:
    """A module that declared a token twice reads back as a list, exactly like a list."""

    [contract] = _compile_routes(_StandardController, _AS_TWO_ENTRIES)

    provider = cast(GlobalPipelineProvider, contract.pipeline_plan.interceptors[0])
    assert provider.declared_component == [_PassThroughInterceptor, _BodyRewritingInterceptor]
    assert provider.label == "_PassThroughInterceptor, _BodyRewritingInterceptor"


def test_a_global_interceptor_only_a_factory_can_produce_is_still_not_read() -> None:
    """A factory names no component before a request exists, and its dependencies are not one.

    A factory an author wrote is shaped like the binding that joins several declarations,
    and the tokens it injects are its own dependencies rather than components declared for
    the slot. Reading them would refuse a raw route over something the module never
    declared as an interceptor at all.
    """

    [contract] = _compile_routes(
        _RawController,
        [
            ClassProvider(provide=_BodyRewritingInterceptor, use_class=_BodyRewritingInterceptor),
            FactoryProvider(
                provide=APP_INTERCEPTOR,
                use_factory=_return_the_interceptor,
                inject=(_BodyRewritingInterceptor,),
            ),
        ],
    )

    provider = cast(GlobalPipelineProvider, contract.pipeline_plan.interceptors[0])
    assert provider.declared_component is None
    assert contract.response_plan.strategy is ResponseStrategy.RAW


def test_a_global_interceptor_declared_as_an_alias_names_no_component() -> None:
    """An alias holds the token it points at, which is neither a component nor a join."""

    [contract] = _compile_routes(
        _RawController,
        [
            ClassProvider(provide=_PassThroughInterceptor, use_class=_PassThroughInterceptor),
            ExistingProvider(provide=APP_INTERCEPTOR, use_existing=_PassThroughInterceptor),
        ],
    )

    provider = cast(GlobalPipelineProvider, contract.pipeline_plan.interceptors[0])
    assert provider.declared_component is None
    assert contract.response_plan.strategy is ResponseStrategy.RAW


@pytest.mark.parametrize(
    "providers",
    [_AS_A_LIST, _AS_ONE_ENTRY, _AS_TWO_ENTRIES, _AS_TWO_MIXED_ENTRIES],
    ids=["list", "one entry", "two entries", "two mixed entries"],
)
def test_a_standard_route_accepts_a_body_mutating_global_interceptor_in_every_spelling(
    providers: list[Provider],
) -> None:
    """The refusal is about the raw strategy, so no spelling of it touches a standard route."""

    [contract] = _compile_routes(_StandardController, providers)

    assert contract.response_plan.strategy is ResponseStrategy.STANDARD


def test_the_compiled_response_plan_drops_the_slots_no_compiler_path_ever_filled() -> None:
    """A plan field that nothing writes cannot be told apart from an unfinished feature.

    A header list, a redirect target and a raw-response parameter name were carried on
    every plan and left at their defaults by every path that builds one, so no route
    could produce a plan holding any of them and no reader could rely on one being set.
    A handler reaches a response header and a redirect by returning a response itself.
    """

    plan_fields = {field.name for field in fields(ResponsePlan)}

    assert "headers" not in plan_fields
    assert "redirect_to" not in plan_fields
    assert "raw_response_parameter" not in plan_fields
