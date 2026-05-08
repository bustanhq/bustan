"""Helpers for assembling test modules and applications."""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast

from ..app.application import Application
from ..app.bootstrap import create_app
from ..core.lifecycle.runner import run_bootstrap_hooks, run_destroy_hooks, run_init_hooks, run_shutdown_hooks
from ..core.module.decorators import Module
from ..core.module.dynamic import ModuleKey
from .overrides import PipelineOverrideRegistry


@dataclass(frozen=True, slots=True)
class _ProviderOverrideSpec:
    kind: str
    value: object
    inject: tuple[object, ...] = ()


class _ProviderOverrideChain:
    def __init__(self, builder: TestingModuleBuilder, token: object) -> None:
        self._builder = builder
        self._token = token

    def use_value(self, value: object) -> TestingModuleBuilder:
        self._builder._provider_overrides[self._token] = _ProviderOverrideSpec("value", value)
        return self._builder

    def use_class(self, value: type[object]) -> TestingModuleBuilder:
        self._builder._provider_overrides[self._token] = _ProviderOverrideSpec("class", value)
        return self._builder

    def use_factory(
        self,
        factory: Callable[..., object],
        *,
        inject: tuple[object, ...] = (),
    ) -> TestingModuleBuilder:
        self._builder._provider_overrides[self._token] = _ProviderOverrideSpec(
            "factory",
            factory,
            inject,
        )
        return self._builder


class _PipelineOverrideChain:
    def __init__(self, mapping: dict[object, object], original: object) -> None:
        self._mapping = mapping
        self._original = original

    def use_value(self, replacement: object) -> None:
        self._mapping[self._original] = replacement

    def use_class(self, replacement: object) -> None:
        self._mapping[self._original] = replacement


class CompiledTestingModule:
    """Compiled application and container wrapper for tests."""

    def __init__(
        self,
        application: Application,
        module_instances: Mapping[ModuleKey, object],
    ) -> None:
        self.application = application
        self._module_instances = module_instances

    def get(self, token: object) -> Any:
        return self.application.get(token)

    def resolve(self, token: object) -> Any:
        return self.get(token)

    def snapshot_routes(self) -> tuple[dict[str, object], ...]:
        return self.application.snapshot_routes()

    def diff_routes(
        self,
        previous_snapshot: Iterable[Mapping[str, object]],
    ) -> tuple[dict[str, object], ...]:
        return self.application.diff_routes(tuple(previous_snapshot))

    def create_client(self):
        from starlette.testclient import TestClient

        return TestClient(cast(Any, self.application))

    async def close(self) -> None:
        await run_shutdown_hooks(
            self.application.module_graph,
            self.application.container,
            self._module_instances,
        )
        await run_destroy_hooks(
            self.application.module_graph,
            self.application.container,
            self._module_instances,
        )


class TestingModuleBuilder:
    """Fluent builder for testing applications and container overrides."""

    __test__ = False

    def __init__(self, root_module: type[object]) -> None:
        self._root_module = root_module
        self._provider_overrides: dict[object, _ProviderOverrideSpec] = {}
        self._pipeline_overrides = PipelineOverrideRegistry()

    def override_provider(self, token: object) -> _ProviderOverrideChain:
        return _ProviderOverrideChain(self, token)

    def override_guard(self, original: object) -> _PipelineOverrideChain:
        return _PipelineOverrideChain(self._pipeline_overrides.guards, original)

    def override_pipe(self, original: object) -> _PipelineOverrideChain:
        return _PipelineOverrideChain(self._pipeline_overrides.pipes, original)

    def override_interceptor(self, original: object) -> _PipelineOverrideChain:
        return _PipelineOverrideChain(self._pipeline_overrides.interceptors, original)

    def override_filter(self, original: object) -> _PipelineOverrideChain:
        return _PipelineOverrideChain(self._pipeline_overrides.filters, original)

    async def compile(self) -> CompiledTestingModule:
        application = create_app(
            self._root_module,
            pipeline_override_registry=self._pipeline_overrides,
            _no_lifespan=True,
        )
        container = application.container
        root_key = application.root_key

        for token, spec in self._provider_overrides.items():
            if spec.kind == "value":
                replacement = spec.value
            elif spec.kind == "class":
                replacement = container.instantiate_class(
                    cast(type[object], spec.value),
                    module=root_key,
                )
            else:
                replacement = container.call_factory(
                    cast(Callable[..., object], spec.value),
                    spec.inject,
                    module=root_key,
                )
            container.override(token, replacement)

        module_instances = await run_init_hooks(application.module_graph, container)
        await run_bootstrap_hooks(application.module_graph, container, module_instances)
        return CompiledTestingModule(
            application,
            MappingProxyType(dict(module_instances.items())),
        )


def create_testing_module(root_module: type[object]) -> TestingModuleBuilder:
    """Create a testing-module builder for the supplied root module."""
    return TestingModuleBuilder(root_module)


def create_test_module(
    *,
    name: str = "TestModule",
    imports: Iterable[type[object]] | None = None,
    controllers: Iterable[type[object]] | None = None,
    providers: Iterable[type[object] | dict[str, object]] | None = None,
    exports: Iterable[object] | None = None,
) -> type[object]:
    """Create a throwaway decorated module for isolated tests."""

    test_module_cls = cast(type[object], type(name, (), {}))
    return Module(
        imports=imports,
        controllers=controllers,
        providers=providers,
        exports=exports,
    )(test_module_cls)


def create_test_app(
    root_module: type[object],
    *,
    provider_overrides: Mapping[object, object] | None = None,
) -> Application:
    """Create an application and apply any requested provider overrides."""

    application = create_app(root_module)

    if provider_overrides is not None:
        for token, replacement in provider_overrides.items():
            # Use internal container for testing overrides
            application._container.override(token, replacement)

    return application
