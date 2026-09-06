from typing import cast

import pytest

from bustan import Controller, Get, Injectable, Module, create_app
from bustan.kernel.errors import (
    InvalidModuleError,
    ModuleCycleError,
)
from bustan.kernel.ioc.container import build_container
from bustan.kernel.module.dynamic import DynamicModule, ModuleInstanceKey
from bustan.kernel.module.graph import build_module_graph


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


def test_dynamic_module_instances_are_distinct_and_their_colliding_exports_are_refused() -> None:
    # Two instances of one base module are separate identities, so each may bind its
    # own tokens. What the importer cannot be given is one name bound twice: nothing in
    # the declaration says which instance wins, so the graph is refused rather than
    # settled by the order the modules happened to be visited.
    @Module()
    class ConfigModule:
        pass

    dynamic1 = DynamicModule(
        ConfigModule, providers=({"provide": "A", "use_value": 1},), exports=("A",)
    )
    dynamic2 = DynamicModule(
        ConfigModule, providers=({"provide": "B", "use_value": 2},), exports=("B",)
    )

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

    # The same two identities, now colliding on one token, cannot be assembled at all.
    colliding1 = DynamicModule(
        ConfigModule, providers=({"provide": "A", "use_value": 1},), exports=("A",)
    )
    colliding2 = DynamicModule(
        ConfigModule, providers=({"provide": "A", "use_value": 2},), exports=("A",)
    )

    @Module(imports=[colliding1, colliding2])
    class CollidingAppModule:
        pass

    with pytest.raises(InvalidModuleError, match="'A'"):
        create_app(CollidingAppModule)


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

    # Two registrations that declare different things are two modules, each with its
    # own singletons.
    dynamic1 = DynamicModule(SharedModule, providers=({"provide": "label", "use_value": "one"},))
    dynamic2 = DynamicModule(SharedModule, providers=({"provide": "label", "use_value": "two"},))

    # Use intermediate modules to avoid provider ambiguity in AppModule
    @Module(imports=[dynamic1])
    class M1:
        pass

    @Module(imports=[dynamic2])
    class M2:
        pass

    app = create_app(DynamicModule(AppModule, imports=(M1, M2)))

    # Use internal container for module-specific resolution in tests
    inst1 = cast(Counter, app._container.resolve(Counter, module=M1))
    inst2 = cast(Counter, app._container.resolve(Counter, module=M2))

    assert inst1 is not inst2
    inst1.count += 1
    assert inst1.count == 1
    assert inst2.count == 0


def test_equal_dynamic_registrations_are_one_module_with_one_set_of_singletons() -> None:
    # A registration is described by its values, so declaring the same one twice
    # describes one module. Building two would give the application two copies of
    # every provider inside it, and a caller reaching one copy would never see what
    # the other recorded.
    @Injectable
    class Counter:
        def __init__(self) -> None:
            self.count = 0

    @Module(providers=[Counter], exports=[Counter])
    class SharedModule:
        pass

    first = DynamicModule(SharedModule, providers=({"provide": "label", "use_value": "same"},))
    second = DynamicModule(SharedModule, providers=({"provide": "label", "use_value": "same"},))

    assert first is second

    @Module(imports=[first])
    class M1:
        pass

    @Module(imports=[second])
    class M2:
        pass

    @Module(imports=[M1, M2])
    class AppModule:
        pass

    graph = build_module_graph(AppModule)
    container = build_container(graph)

    shared_nodes = [node.key for node in graph.nodes if node.module is SharedModule]

    assert len(shared_nodes) == 1
    assert container.resolve(Counter, module=M1) is container.resolve(Counter, module=M2)


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


def test_dynamic_module_nested_expansion_resolves_the_reexported_provider() -> None:
    # A module that re-exports a token it imported is promising the importer an
    # instance, not a name. Visibility that no binding backs is a promise kept only
    # until the first request, so the re-exported token resolves through the
    # importing module or it was never exported at all.
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

    @Module(imports=[top_dynamic])
    class AppModule:
        pass

    app = create_app(AppModule)

    assert isinstance(app._container.resolve(DeepService, module=AppModule), DeepService)


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

    # Verify both controllers work via internal module graph access
    graph = app._container.module_graph
    assert len(graph.get_node(graph.root_key).controllers) == 2

    # Verify routes via public accessor
    server = app.get_http_server()
    paths = {r.path for r in server.routes if hasattr(r, "path")}
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


def test_registrations_holding_a_value_nothing_can_hash_stay_apart() -> None:
    # A declaration is matched by its values, and a value nothing can hash cannot be
    # compared to another. Standing for itself is the strictest answer available, so
    # two such declarations are never merged by mistake.
    @Module(providers=[], exports=[])
    class SharedModule:
        pass

    first = DynamicModule(SharedModule, providers=({"provide": "tags", "use_value": {"a", "b"}},))
    second = DynamicModule(SharedModule, providers=({"provide": "tags", "use_value": {"a", "b"}},))

    assert first is not second
