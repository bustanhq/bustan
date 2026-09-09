"""The awaited half of the kernel, against the same graphs the synchronous half uses.

Sync and async resolution used to be eight near-duplicate method pairs that had
already drifted apart, so these tests exist to hold the two answers together: the
decisions are taken once and only the waiting differs.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Annotated, Any, cast

import anyio
import pytest
from starlette.requests import Request

from bustan import FactoryProvider, Injectable, Module, Scope, create_app_context
from bustan.common.decorators.injectable import Inject
from bustan.errors import ProviderResolutionError
from bustan.kernel.ioc.container import build_container
from bustan.kernel.module.graph import build_module_graph

if TYPE_CHECKING:
    from tests.conftest import HttpRequestFactory

CONNECTION = "connection"


@Injectable
class Dependency:
    """A provider with nothing of its own to resolve."""


def test_a_class_is_instantiated_with_awaited_dependencies() -> None:
    async def open_connection() -> str:
        return "connected"

    class Consumer:
        def __init__(self, connection: Annotated[str, Inject(CONNECTION)]) -> None:
            self.connection = connection

    @Module(
        providers=[FactoryProvider(provide=CONNECTION, use_factory=open_connection)],
        exports=[CONNECTION],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    async def build() -> object:
        return await container.instantiate_class_async(Consumer, module=AppModule)

    assert cast(Any, anyio.run(build)).connection == "connected"


def test_a_factory_called_asynchronously_awaits_both_itself_and_its_dependencies() -> None:
    async def open_connection() -> str:
        return "connected"

    async def describe(connection: str) -> str:
        return f"using {connection}"

    @Module(
        providers=[FactoryProvider(provide=CONNECTION, use_factory=open_connection)],
        exports=[CONNECTION],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    async def call() -> object:
        return await container.call_factory_async(describe, (CONNECTION,), module=AppModule)

    assert anyio.run(call) == "using connected"


def test_a_synchronous_factory_called_asynchronously_is_not_awaited() -> None:
    def describe() -> str:
        return "plain"

    @Module()
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    async def call() -> object:
        return await container.call_factory_async(describe, (), module=AppModule)

    assert anyio.run(call) == "plain"


def test_an_awaited_singleton_is_constructed_once_under_its_own_lock() -> None:
    constructions: list[int] = []

    async def open_connection() -> str:
        constructions.append(1)
        await anyio.sleep(0)
        return "connected"

    @Module(
        providers=[FactoryProvider(provide=CONNECTION, use_factory=open_connection)],
        exports=[CONNECTION],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    resolved: list[object] = []

    async def resolve_concurrently() -> None:
        async with anyio.create_task_group() as tasks:
            for _ in range(4):
                tasks.start_soon(_append_resolution, container, AppModule, resolved)

    anyio.run(resolve_concurrently)

    assert len(constructions) == 1
    assert resolved == ["connected"] * 4


async def _append_resolution(container: object, module: object, resolved: list[object]) -> None:
    resolved.append(await cast(Any, container).resolve_async(CONNECTION, module=module))


def test_an_awaited_failure_still_names_the_owner_and_the_path() -> None:
    @Injectable
    class Consumer:
        def __init__(self, dependency: Dependency) -> None:
            self.dependency = dependency

    @Module(providers=[Consumer, Dependency], exports=[Consumer])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    # Removing the binding after the graph was planned is the only way to reach the
    # failure path from a graph that planned cleanly; it stands for a token whose
    # binding the runtime cannot find. Nothing in the framework removes a binding, so
    # the test reaches into the table rather than a removal method existing for it.
    del container.registry._bindings[(AppModule, Dependency)]

    async def resolve() -> object:
        return await container.resolve_async(Consumer, module=AppModule)

    with pytest.raises(ProviderResolutionError, match="failed to resolve"):
        anyio.run(resolve)


def test_a_request_scoped_provider_resolves_asynchronously_for_its_own_request(
    build_http_request: HttpRequestFactory,
) -> None:
    @Injectable(scope=Scope.REQUEST)
    class Identity:
        def __init__(self, request: Request) -> None:
            self.user = request.headers.get("x-user-id", "anonymous")

    @Module(providers=[Identity], exports=[Identity])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    request = build_http_request(path="/me", headers=[(b"x-user-id", b"alice")])

    async def resolve() -> tuple[object, object]:
        return (
            await container.resolve_async(Identity, module=AppModule, request=request),
            await container.resolve_async(Identity, module=AppModule, request=request),
        )

    first, second = cast("tuple[Any, Any]", anyio.run(resolve))

    assert first is second
    assert first.user == "alice"


def test_an_async_provider_that_returns_none_starts_a_standalone_context() -> None:
    async def build_client() -> None:
        return None

    @Module(
        providers=[FactoryProvider(provide="client", use_factory=build_client)], exports=["client"]
    )
    class AppModule:
        pass

    async def start() -> object:
        context = await create_app_context(AppModule).init()
        return context.get("client")

    assert anyio.run(start) is None


def test_a_singleton_built_from_both_drivers_at_once_is_built_once() -> None:
    # The two drivers wait in different ways and must still wait for each other. A
    # sequential pair of resolutions cannot show this: the second one finds the first
    # one's instance in the cache and never reaches the lock at all.
    constructions: list[object] = []

    @Injectable
    class ConnectionPool:
        def __init__(self) -> None:
            constructions.append(object())
            # Long enough that the awaited resolution below starts while this one is
            # still inside the constructor, which is the only moment the two can race.
            time.sleep(0.3)

    @Module(providers=[ConnectionPool], exports=[ConnectionPool])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    built: dict[str, object] = {}

    def resolve_synchronously() -> None:
        built["sync"] = container.resolve(ConnectionPool, module=AppModule)

    async def race() -> None:
        thread = threading.Thread(target=resolve_synchronously)
        thread.start()
        await anyio.sleep(0.05)
        built["async"] = await container.resolve_async(ConnectionPool, module=AppModule)
        thread.join()

    anyio.run(race)

    assert len(constructions) == 1
    assert built["sync"] is built["async"]


def test_waiting_for_a_singleton_another_thread_is_building_leaves_the_loop_running() -> None:
    # Both drivers hold the same lock, and the awaited one must hold it without
    # stalling the event loop it is running on, or one slow constructor in a worker
    # thread would stop every other request the process is serving.
    @Injectable
    class SlowService:
        def __init__(self) -> None:
            time.sleep(0.3)

    @Module(providers=[SlowService], exports=[SlowService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    ticks: list[int] = []
    waited: list[float] = []

    def resolve_synchronously() -> None:
        container.resolve(SlowService, module=AppModule)

    async def tick() -> None:
        while True:
            await anyio.sleep(0.01)
            ticks.append(len(ticks))

    async def race() -> None:
        thread = threading.Thread(target=resolve_synchronously)
        thread.start()
        await anyio.sleep(0.05)
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(tick)
            started = time.perf_counter()
            await container.resolve_async(SlowService, module=AppModule)
            waited.append(time.perf_counter() - started)
            task_group.cancel_scope.cancel()
        thread.join()

    anyio.run(race)

    # It really waited for the other driver rather than building its own instance.
    assert waited[0] > 0.1
    # And the loop kept running while it waited. A tenth of a second of waiting at a
    # ten-millisecond tick is around ten of them; three is the floor a loaded machine
    # still clears, and a loop stalled on the lock produces none at all.
    assert len(ticks) >= 3


def test_two_resolutions_at_once_inside_one_request_share_one_instance(
    build_http_request: HttpRequestFactory,
) -> None:
    # A request-scoped provider is private to its request, so nothing serializes the
    # two resolutions against each other; the cache is what has to refuse the second
    # instance, or the request holds two of what it was promised one of. The factory is
    # awaited, which is what lets the second resolution start while the first is still
    # inside it and find the same empty cache.
    async def open_identity() -> object:
        await anyio.sleep(0.05)
        return object()

    @Module(
        providers=[
            FactoryProvider(provide="identity", use_factory=open_identity, scope=Scope.REQUEST)
        ],
        exports=["identity"],
    )
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    request = build_http_request(path="/me")
    resolved: list[object] = []

    async def resolve() -> None:
        resolved.append(
            await container.resolve_async("identity", module=AppModule, request=request)
        )

    async def race() -> None:
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(resolve)
            task_group.start_soon(resolve)

    anyio.run(race)

    assert len(resolved) == 2
    assert resolved[0] is resolved[1]


def test_a_resolution_cancelled_while_it_waits_gives_the_lock_back() -> None:
    # Waiting for the other driver happens off the event loop, and a cancellation
    # reaches the waiter only once that wait has finished - by which time the waiter
    # may hold the lock. Giving it back is what keeps a caller that walked away from
    # leaving the provider unbuildable for everyone after it.
    @Injectable
    class SlowService:
        def __init__(self) -> None:
            time.sleep(0.3)

    @Module(providers=[SlowService], exports=[SlowService])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))

    def resolve_synchronously() -> None:
        container.resolve(SlowService, module=AppModule)

    async def resolve_and_walk_away() -> None:
        await container.resolve_async(SlowService, module=AppModule)

    async def abandon() -> None:
        thread = threading.Thread(target=resolve_synchronously)
        thread.start()
        await anyio.sleep(0.05)
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(resolve_and_walk_away)
            await anyio.sleep(0.05)
            task_group.cancel_scope.cancel()
        thread.join()

    async def resolve_after() -> object:
        await abandon()
        return await container.resolve_async(SlowService, module=AppModule)

    assert isinstance(anyio.run(resolve_after), SlowService)
