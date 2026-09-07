import asyncio

from bustan.testing import create_testing_module

from $package_name.app_controller import AppController
from $package_name.app_module import AppModule
from $package_name.app_service import AppService


async def _check_module_wiring() -> None:
    compiled = await create_testing_module(AppModule).compile()
    try:
        routes = compiled.snapshot_routes()
        assert len(routes) == 1
        assert routes[0]["controller"] == AppController.__name__
        assert routes[0]["path"] == "/"
        assert isinstance(compiled.get(AppService), AppService)
    finally:
        await compiled.close()


def test_app_module_registers_controller_and_provider() -> None:
    # Compiling the module and shutting it back down are both asynchronous, and this
    # project depends on pytest alone, so the coroutine is driven here rather than by
    # a plugin that would be needed to collect an asynchronous test function.
    asyncio.run(_check_module_wiring())
