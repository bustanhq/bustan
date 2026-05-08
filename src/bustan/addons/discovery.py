"""Read-only discovery surfaces for modules, providers, and routes."""

from __future__ import annotations

from typing import Annotated

from starlette.applications import Starlette

from ..app.application import Application
from ..common.decorators.injectable import Inject, Injectable
from ..common.types import ProviderScope
from ..core.ioc.tokens import APPLICATION
from ..core.module.decorators import Module
from ..core.module.dynamic import ModuleKey
from ..core.utils import _display_name
from .module_ref import ModuleRef


@Injectable(scope=ProviderScope.TRANSIENT)
class DiscoveryService:
    """Read-only inspection surface for compiled modules, providers, and routes."""

    def __init__(self, application: Annotated[object, Inject(APPLICATION)]) -> None:
        self._application = _resolve_application_context(application)

    def modules(self) -> tuple[dict[str, object], ...]:
        entries: list[dict[str, object]] = []
        for node in sorted(self._application.module_graph.nodes, key=lambda node: _display_name(node.key)):
            entries.append(
                {
                    "module": _display_name(node.key),
                    "global": node.metadata.is_global,
                    "imports": tuple(sorted(_display_name(module) for module in node.imports)),
                    "controllers": tuple(sorted(controller.__name__ for controller in node.controllers)),
                    "providers": tuple(sorted(_display_name(binding.token) for binding in node.bindings)),
                    "exports": tuple(sorted(_display_name(token) for token in node.exports)),
                }
            )
        return tuple(entries)

    def providers(self) -> tuple[dict[str, object], ...]:
        entries: list[dict[str, object]] = []
        for node in sorted(self._application.module_graph.nodes, key=lambda node: _display_name(node.key)):
            entries.extend(self.providers_for_module(node.key))
        return tuple(entries)

    def providers_for_module(self, module: ModuleKey | type[object]) -> tuple[dict[str, object], ...]:
        node = _resolve_module_node(self._application.module_graph.nodes, module)
        bindings = sorted(node.bindings, key=lambda binding: _display_name(binding.token))
        return tuple(
            {
                "module": _display_name(node.key),
                "token": _display_name(binding.token),
                "scope": binding.scope.value,
                "resolver": binding.resolver_kind,
                "exported": binding.token in node.exported_providers,
            }
            for binding in bindings
        )

    def routes(self) -> tuple[dict[str, object], ...]:
        return self._application.snapshot_routes()


@Module(providers=[DiscoveryService, ModuleRef], exports=[DiscoveryService, ModuleRef])
class DiscoveryModule:
    """Addon module that exposes the read-only DiscoveryService."""

    pass


def _resolve_application_context(application: object) -> Application:
    if isinstance(application, Application):
        return application
    if isinstance(application, Starlette):
        runtime = getattr(application.state, "bustan_application", None)
        if isinstance(runtime, Application):
            return runtime
    raise TypeError("DiscoveryService requires an Application runtime")


def _resolve_module_node(
    nodes: tuple[object, ...],
    module: ModuleKey | type[object],
):
    for node in nodes:
        if getattr(node, "key", None) == module or getattr(node, "module", None) is module:
            return node
    raise KeyError(f"Unknown module {module!r}")
