import pytest
from typing import Any, cast
from bustan import Controller, DynamicModule, Get, Injectable, Module, create_app
from bustan.errors import (
    ModuleCycleError,
)
from bustan.metadata import ModuleInstanceKey
from bustan.module_graph import ModuleGraph, build_module_graph


def test_dynamic_module_merges_metadata() -> None:
    @Injectable
    class StaticService:
        pass

    @Injectable
    class DynamicService:
        pass

    @Module(providers=[StaticService])
    class BaseModule:
        pass

    dynamic = DynamicModule(BaseModule, providers=(DynamicService,))
    graph = build_module_graph(dynamic)

    # Root should be the dynamic instance
    root_node = graph.get_node(graph.root_key)
    assert StaticService in root_node.available_providers
    assert DynamicService in root_node.available_providers
    assert len(root_node.bindings) == 2


def test_dynamic_module_unique_identities() -> None:
    @Module()
    class ConfigModule:
        pass

    dynamic1 = DynamicModule(ConfigModule, providers=({"provide": "A", "use_value": 1},))
    dynamic2 = DynamicModule(ConfigModule, providers=({"provide": "A", "use_value": 2},))

    @Module(imports=[dynamic1, dynamic2])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)

    # We should have 1 AppModule and 2 unique ConfigModule instances
    assert len(graph.nodes) == 3

    app_node = graph.get_node(AppModule)
    imported_keys = list(app_node.imported_exports.keys())
    assert len(imported_keys) == 2
    assert imported_keys[0] != imported_keys[1]

    k0 = imported_keys[0]
    k1 = imported_keys[1]
    assert isinstance(k0, ModuleInstanceKey) and k0.module is ConfigModule
    assert isinstance(k1, ModuleInstanceKey) and k1.module is ConfigModule


def test_dynamic_module_singleton_isolation() -> None:
    @Injectable
    class Counter:
        def __init__(self):
            self.count = 0

    @Module(providers=[Counter], exports=[Counter])
    class SharedModule:
        pass

    @Module()
    class AppModule:
        pass

    dynamic1 = DynamicModule(SharedModule)
    dynamic2 = DynamicModule(SharedModule)

    # Use intermediate modules to avoid provider ambiguity in AppModule
    @Module(imports=[dynamic1])
    class M1:
        pass

    @Module(imports=[dynamic2])
    class M2:
        pass

    app = create_app(DynamicModule(AppModule, imports=(M1, M2)))

    inst1 = cast(Counter, app.container.resolve(Counter, module=M1))
    inst2 = cast(Counter, app.container.resolve(Counter, module=M2))

    assert inst1 is not inst2
    inst1.count += 1
    assert inst1.count == 1
    assert inst2.count == 0


def test_dynamic_module_circular_dependency() -> None:
    @Module()
    class ModuleA:
        pass

    dynamic_cycle = DynamicModule(ModuleA)
    # Patching metadata manually to create a cycle for testing purposes
    # since DynamicModule is frozen. This simulates a recursive structure.
    object.__setattr__(dynamic_cycle, "imports", (dynamic_cycle,))

    with pytest.raises(ModuleCycleError, match="Circular module dependency detected"):
        build_module_graph(dynamic_cycle)


def test_dynamic_module_nested_expansion() -> None:
    @Injectable
    class DeepService:
        pass

    @Module(providers=[DeepService], exports=[DeepService])
    class BottomModule:
        pass

    mid_dynamic = DynamicModule(BottomModule)

    @Module(imports=[mid_dynamic], exports=[DeepService])
    class MidModule:
        pass

    top_dynamic = DynamicModule(MidModule)

    graph = build_module_graph(top_dynamic)
    assert len(graph.nodes) == 2  # TopDynamic -> MidDynamic

    # Verify DeepService is available at the top
    top_node = graph.get_node(graph.root_key)
    assert DeepService in top_node.available_providers


def test_dynamic_module_controller_addition() -> None:
    @Injectable
    class DataService:
        def get_data(self):
            return "ok"

    @Controller("/static")
    class StaticController:
        def __init__(self, ds: DataService):
            self.ds = ds

        @Get("/")
        def index(self):
            return self.ds.get_data()

    @Controller("/dynamic")
    class DynamicController:
        def __init__(self, ds: DataService):
            self.ds = ds

        @Get("/")
        def index(self):
            return self.ds.get_data()

    @Module(controllers=[StaticController], providers=[DataService])
    class RootModule:
        pass

    dynamic = DynamicModule(RootModule, controllers=(DynamicController,))
    app = create_app(dynamic)

    # Verify both controllers work
    graph = cast(ModuleGraph, app.module_graph)
    assert len(graph.get_node(graph.root_key).controllers) == 2

    # We can check route count
    routes = app._starlette_app.routes
    paths = {cast(Any, r).path for r in routes}
    assert "/static" in paths
    assert "/dynamic" in paths


def test_dynamic_module_export_merging() -> None:
    @Injectable
    class S1:
        pass

    @Injectable
    class S2:
        pass

    @Module(providers=[S1], exports=[S1])
    class Base:
        pass

    dynamic = DynamicModule(Base, providers=(S2,), exports=(S2,))

    @Module(imports=[dynamic])
    class App:
        pass

    graph = build_module_graph(App)
    app_node = graph.get_node(App)

    # Find the dynamic key
    dyn_key = list(app_node.imported_exports.keys())[0]
    exports = app_node.imported_exports[dyn_key]

    assert S1 in exports
    assert S2 in exports
