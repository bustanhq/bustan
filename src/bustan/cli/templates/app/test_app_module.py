import asyncio

from bustan.testing import create_testing_module

from $package_name.app_controller import AppController
from $package_name.app_module import AppModule
from $package_name.app_service import AppService


async def _check_module_wiring() -> None:
    compiled = await create_testing_module(AppModule).compile()
    try:
        # The root controller is looked for among the routes rather than counted,
        # because each module the project adds brings routes of its own.
        routes = compiled.snapshot_routes()
        served = {(route["controller"], route["path"]) for route in routes}
        assert (AppController.__name__, "/") in served
        assert isinstance(compiled.get(AppService), AppService)
    finally:
        await compiled.close()


def test_app_module_registers_controller_and_provider() -> None:
    # Compiling the module and shutting it back down are both asynchronous, and this
    # project depends on pytest alone, so the coroutine is driven here rather than by
    # a plugin that would be needed to collect an asynchronous test function.
    asyncio.run(_check_module_wiring())
