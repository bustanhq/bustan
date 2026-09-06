"""Helpers for assembling test modules and applications."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast

from ..app.application import Application
from ..app.bootstrap import _create_app, create_app
from ..kernel.errors import LifecycleError
from ..kernel.ioc.container import Container
from ..kernel.ioc.registry import token_identity
from ..kernel.lifecycle.manager import LifecycleManager
from ..kernel.module.decorators import Module
from ..kernel.module.dynamic import ModuleKey
from .overrides import PipelineOverrideRegistry


@dataclass(frozen=True, slots=True)
class _ValueOverride:
    value: object


@dataclass(frozen=True, slots=True)
class _ClassOverride:
    replacement_cls: type[object]


@dataclass(frozen=True, slots=True)
class _FactoryOverride:
    factory: Callable[..., object]
    inject: tuple[object, ...]


_ProviderOverride = _ValueOverride | _ClassOverride | _FactoryOverride


class _ProviderOverrideChain:
    def __init__(self, builder: TestingModuleBuilder, token: object) -> None:
        self._builder = builder
        self._token = token

    def use_value(self, value: object) -> TestingModuleBuilder:
        self._builder._provider_overrides[self._token] = _ValueOverride(value)
        return self._builder

    def use_class(self, value: type[object]) -> TestingModuleBuilder:
        self._builder._provider_overrides[self._token] = _ClassOverride(value)
        return self._builder

    def use_factory(
        self,
        factory: Callable[..., object],
        *,
        inject: tuple[object, ...] = (),
    ) -> TestingModuleBuilder:
        self._builder._provider_overrides[self._token] = _FactoryOverride(factory, inject)
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

    @property
    def module_instances(self) -> Mapping[ModuleKey, object]:
        """The module instances the startup sequence built, keyed by module."""
        return self._module_instances

    def get(self, token: object) -> Any:
        """Resolve a provider from the root module context."""
        return self.application.get(token)

    def resolve(self, token: object) -> Any:
        """Alias for get()."""
        return self.get(token)

    def snapshot_routes(self) -> tuple[dict[str, object], ...]:
        """Return a deterministic snapshot of the compiled application routes."""
        return self.application.snapshot_routes()

    def diff_routes(
        self,
        previous_snapshot: Iterable[Mapping[str, object]],
    ) -> tuple[dict[str, object], ...]:
        """Compare a previous route snapshot against the current application routes."""
        return self.application.diff_routes(tuple(previous_snapshot))

    def create_client(self):
        """Return a Starlette test client bound to the compiled application."""
        from starlette.testclient import TestClient

        return TestClient(cast(Any, self.application))

    async def close(self) -> None:
        """Tear the compiled application down through its own lifecycle.

        Teardown belongs to the application's lifecycle manager, so the stages run in
        the order a served application runs them, a second call does nothing, and
        every failing hook is reported rather than only the first one.
        """
        await self.application.close()


class TestingModuleBuilder:
    """Fluent builder for testing applications and container overrides."""

    __test__ = False

    def __init__(self, root_module: type[object]) -> None:
        self._root_module = root_module
        self._provider_overrides: dict[object, _ProviderOverride] = {}
        self._pipeline_overrides = PipelineOverrideRegistry()

    def override_provider(self, token: object) -> _ProviderOverrideChain:
        """Begin replacing the provider bound to a token."""
        return _ProviderOverrideChain(self, token)

    def override_guard(self, original: object) -> _PipelineOverrideChain:
        """Begin replacing a guard class wherever the application declares it."""
        return _PipelineOverrideChain(self._pipeline_overrides.guards, original)

    def override_pipe(self, original: object) -> _PipelineOverrideChain:
        """Begin replacing a pipe class wherever the application declares it."""
        return _PipelineOverrideChain(self._pipeline_overrides.pipes, original)

    def override_interceptor(self, original: object) -> _PipelineOverrideChain:
        """Begin replacing an interceptor class wherever the application declares it."""
        return _PipelineOverrideChain(self._pipeline_overrides.interceptors, original)

    def override_filter(self, original: object) -> _PipelineOverrideChain:
        """Begin replacing a filter class wherever the application declares it."""
        return _PipelineOverrideChain(self._pipeline_overrides.filters, original)

    async def compile(self) -> CompiledTestingModule:
        """Build the application, apply every override, and run its startup sequence.

        Startup is the application's own, so a graph a served application can start is
        a graph a test can start: async singleton factories are warmed before any hook
        runs, and the lifecycle manager knows afterwards that startup has happened.
        """
        application = _create_app(
            self._root_module,
            pipeline_override_registry=self._pipeline_overrides,
            no_lifespan=True,
        )
        lifecycle = _require_lifecycle_manager(application)

        await self._register_overrides(application.container)

        module_instances = await lifecycle.startup()
        return CompiledTestingModule(
            application,
            MappingProxyType(dict(module_instances.items())),
        )

    async def _register_overrides(self, container: Container) -> None:
        """Register every requested replacement before the lifecycle starts.

        Values are registered first because a class or factory replacement may depend
        on a token that is itself replaced by value, and it must be handed the
        replacement rather than the provider standing in for it. Every replacement is
        in place before startup, so warm-up and the init hooks see the test's graph.
        """
        for token, override in self._provider_overrides.items():
            if isinstance(override, _ValueOverride):
                container.override(
                    token, override.value, module=_declaring_module(container, token)
                )

        for token, override in self._provider_overrides.items():
            if isinstance(override, _ValueOverride):
                continue
            # A replacement stands in for the provider it replaces, so it is built
            # with that provider's visibility: from the module that declares the
            # token, never from the root. Building from the root would force a fake
            # to have every dependency exported to the root, and would blame the root
            # module for a dependency the declaring module can see perfectly well.
            declaring = _declaring_module(container, token)
            module = declaring or container.module_graph.root_key
            if isinstance(override, _ClassOverride):
                replacement = await container.instantiate_class_async(
                    override.replacement_cls,
                    module=module,
                )
            else:
                replacement = await container.call_factory_async(
                    override.factory,
                    override.inject,
                    module=module,
                )
            container.override(token, replacement, module=declaring)


def _require_lifecycle_manager(application: Application) -> LifecycleManager:
    """Return an application's lifecycle manager, refusing one that has none.

    The testing surface owns no lifecycle of its own; it drives the application's.
    An application assembled without a manager therefore has no startup to run and
    no teardown to delegate to, and is refused here rather than half-started.
    """
    lifecycle = application._lifecycle_manager
    if lifecycle is None:
        raise LifecycleError(
            "The application was built without a lifecycle manager, so a testing "
            "module cannot start or stop it"
        )
    return lifecycle


def _declaring_module(container: Container, token: object) -> ModuleKey | None:
    """Return the single module that declares a token, or None when that is not one.

    Tokens are compared by identity in the container's sense, which pairs a token
    with its type: a string token built while the test runs is a different object
    from the one the module registered but names the same provider, and a string
    enum member that equals a bare string still names a different one.

    A token bound by no module, or by several, has no unambiguous declaring module.
    Both cases are left to the container's own override registration to refuse, so
    that one component decides what an ambiguous override means and says so once.
    """
    identity = token_identity(token)
    declaring = [
        registered_module
        for registered_module, registered_token in container.registry.bindings
        if token_identity(registered_token) == identity
    ]
    if len(declaring) != 1:
        return None
    return declaring[0]


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
