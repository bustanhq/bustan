"""Unit tests for the application factory."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import pytest
from starlette.applications import Starlette

from bustan import Application, Controller, Get, Injectable, Module, create_app
from bustan.adapters.asgi import AsgiAdapter
from bustan.platform.http.adapter import AdapterFactory, AdapterRuntime


@Module()
class RootModule:
    pass


def test_create_app_basic() -> None:
    app = create_app(RootModule)
    assert isinstance(app, Application)
    server = app.get_http_server()
    assert isinstance(server, Starlette)
    assert server.debug is False


def test_create_app_with_debug() -> None:
    app = create_app(RootModule, debug=True)
    assert app.get_http_server().debug is True


def test_create_app_with_controllers() -> None:
    @Controller("/test")
    class TestController:
        @Get("/")
        def index(self):
            return "ok"

    @Module(controllers=[TestController])
    class AppModule:
        pass

    app = create_app(AppModule)
    # Check routes directly instead of controllers property
    assert "/test" in app.routes
    assert len(app.execution_plans) == 1
    assert app.execution_plans[0].route_contract is app.route_contracts[0]
    assert app.get_http_server().state.bustan_execution_plans == app.execution_plans


def test_an_adapter_instance_is_served_through_exactly_as_it_was_given() -> None:
    adapter = AsgiAdapter()

    app = create_app(RootModule, adapter=adapter)

    assert app.get_http_server() is adapter.get_instance()


def test_an_adapter_factory_receives_debug_and_the_frameworks_lifespan() -> None:
    seen: list[AdapterRuntime] = []

    def build(runtime: AdapterRuntime) -> AsgiAdapter:
        seen.append(runtime)
        return AsgiAdapter(lifespan=runtime.lifespan)

    create_app(RootModule, debug=True, adapter=build)

    assert len(seen) == 1
    assert seen[0].debug is True
    assert seen[0].lifespan is not None


def test_the_lifespan_a_factory_built_adapter_runs_starts_the_module_graph() -> None:
    started: list[str] = []

    @Injectable()
    class Recorder:
        def on_module_init(self) -> None:
            started.append("init")

    @Module(providers=[Recorder])
    class AppModule:
        pass

    adapters: list[AsgiAdapter] = []

    def build(runtime: AdapterRuntime) -> AsgiAdapter:
        adapters.append(AsgiAdapter(lifespan=runtime.lifespan))
        return adapters[-1]

    create_app(AppModule, adapter=build)

    # The client runs the lifespan the framework built, which is the only thing that
    # could have started the module graph: nothing in this test calls init() itself.
    with adapters[0].create_test_client():
        assert started == ["init"]


def test_an_adapter_factory_must_return_an_adapter() -> None:
    # The annotation already rejects this, so the cast is what an untyped caller does;
    # the guard is here because the failure would otherwise surface much further on.
    returns_the_wrong_thing = cast(AdapterFactory, lambda runtime: "not an adapter")

    with pytest.raises(TypeError, match="must return an AbstractHttpAdapter, not str"):
        create_app(RootModule, adapter=returns_the_wrong_thing)


def test_create_app_without_the_starlette_extra_names_the_extra_and_the_command() -> None:
    with _starlette_uninstalled(), pytest.raises(ImportError) as raised:
        create_app(RootModule)

    message = str(raised.value)
    assert "starlette" in message.lower()
    assert "pip install 'bustan[starlette]'" in message
    assert "adapter=" in message
    assert isinstance(raised.value.__cause__, ModuleNotFoundError)


def test_an_unrelated_missing_import_under_the_adapter_is_not_reported_as_the_extra(
    monkeypatch,
) -> None:
    # An import that fails for any reason other than the absent extra must reach the
    # caller as it stands, or the reader is sent to install something already present.
    monkeypatch.setitem(sys.modules, "bustan.adapters.starlette", None)

    with pytest.raises(ModuleNotFoundError) as raised:
        create_app(RootModule)

    assert raised.value.name == "bustan.adapters.starlette"
    assert "pip install" not in str(raised.value)


class _RefuseToImport:
    """A meta path finder that makes one package look absent, as an uninstall would."""

    def __init__(self, package: str) -> None:
        self._package = package

    def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
        if fullname == self._package or fullname.startswith(f"{self._package}."):
            raise ModuleNotFoundError(f"No module named '{fullname}'", name=fullname)
        return None


@contextmanager
def _starlette_uninstalled() -> Iterator[None]:
    """Run the block in a process where Starlette is not installed.

    The adapter package is evicted along with Starlette itself, because an import that
    is already cached never reaches the finder and the absence would go unnoticed. Both
    are put back afterwards, so this leaves the rest of the suite the modules it had.
    """

    evicted = {
        name: module
        for name, module in sys.modules.items()
        if name == "starlette"
        or name.startswith("starlette.")
        or name == "bustan.adapters.starlette"
        or name.startswith("bustan.adapters.starlette.")
    }
    for name in evicted:
        del sys.modules[name]

    finder = _RefuseToImport("starlette")
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        sys.meta_path.remove(finder)
        sys.modules.update(evicted)
