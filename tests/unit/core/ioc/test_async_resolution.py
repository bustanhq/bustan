"""The awaited half of the kernel, against the same graphs the synchronous half uses.

Sync and async resolution used to be eight near-duplicate method pairs that had
already drifted apart, so these tests exist to hold the two answers together: the
decisions are taken once and only the waiting differs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, cast

import anyio
import pytest
from starlette.requests import Request

from bustan import Injectable, Module, Scope, create_app_context
from bustan.common.decorators.injectable import Inject
from bustan.core.ioc.container import build_container
from bustan.core.module.graph import build_module_graph
from bustan.errors import ProviderResolutionError

if TYPE_CHECKING:
    from tests.conftest import RequestFactory

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
        providers=[{"provide": CONNECTION, "use_factory": open_connection}],
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
        providers=[{"provide": CONNECTION, "use_factory": open_connection}],
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
        providers=[{"provide": CONNECTION, "use_factory": open_connection}],
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
    # binding the runtime cannot find.
    del container.registry.bindings[(AppModule, Dependency)]

    async def resolve() -> object:
        return await container.resolve_async(Consumer, module=AppModule)

    with pytest.raises(ProviderResolutionError, match="failed to resolve"):
        anyio.run(resolve)


def test_a_request_scoped_provider_resolves_asynchronously_for_its_own_request(
    build_request: RequestFactory,
) -> None:
    @Injectable(scope=Scope.REQUEST)
    class Identity:
        def __init__(self, request: Request) -> None:
            self.user = request.headers.get("x-user-id", "anonymous")

    @Module(providers=[Identity], exports=[Identity])
    class AppModule:
        pass

    container = build_container(build_module_graph(AppModule))
    request = build_request(path="/me", headers=[(b"x-user-id", b"alice")])

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

    @Module(providers=[{"provide": "client", "use_factory": build_client}], exports=["client"])
    class AppModule:
        pass

    async def start() -> object:
        context = await create_app_context(AppModule).init()
        return context.get("client")

    assert anyio.run(start) is None
