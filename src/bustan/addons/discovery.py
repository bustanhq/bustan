"""Read-only discovery surfaces for modules, providers, and routes."""

from __future__ import annotations

from typing import Annotated

from ..app.application import ApplicationContext
from ..common.decorators.injectable import Inject, Injectable
from ..common.types import ProviderScope
from ..kernel.ioc.tokens import APPLICATION
from ..kernel.module.decorators import Module
from ..kernel.module.dynamic import ModuleKey
from ..kernel.utils import _display_name
from .module_ref import ModuleRef, _application_context


@Injectable(scope=ProviderScope.TRANSIENT)
class DiscoveryService:
    """Read-only inspection surface for compiled modules, providers, and routes."""

    def __init__(self, application: Annotated[ApplicationContext, Inject(APPLICATION)]) -> None:
        self._application = _application_context(application, "DiscoveryService")

    def modules(self) -> tuple[dict[str, object], ...]:
        # Every field of every row is a name, and no field describes what a module was
        # configured with. This surface exists to be called by application code - a
        # health endpoint, an admin page, a support dump - so a row reaches whoever that
        # caller answers, and the providers a module was built with are the values it
        # configures.
        entries: list[dict[str, object]] = []
        for node in sorted(
            self._application.module_graph.nodes, key=lambda node: _module_name(node.key)
        ):
            entries.append(
                {
                    "module": _module_name(node.key),
                    "global": node.metadata.is_global,
                    # An import is named by the key the graph compiled it to and never by
                    # the declaration that produced it, because the declaration of a
                    # module built by a factory is the object holding the providers it
                    # was built with. Every import is resolved to a key and recorded
                    # here, so these keys are exactly this module's imports.
                    "imports": tuple(sorted(_module_name(key) for key in node.imported_exports)),
                    "controllers": tuple(
                        sorted(controller.__name__ for controller in node.controllers)
                    ),
                    "providers": tuple(
                        sorted(_display_name(binding.token) for binding in node.bindings)
                    ),
                    "exports": tuple(sorted(_display_name(token) for token in node.exports)),
                }
            )
        return tuple(entries)

    def providers(self) -> tuple[dict[str, object], ...]:
        entries: list[dict[str, object]] = []
        for node in sorted(
            self._application.module_graph.nodes, key=lambda node: _module_name(node.key)
        ):
            entries.extend(self.providers_for_module(node.key))
        return tuple(entries)

    def providers_for_module(
        self, module: ModuleKey | type[object]
    ) -> tuple[dict[str, object], ...]:
        node = _resolve_module_node(self._application.module_graph.nodes, module)
        bindings = sorted(node.bindings, key=lambda binding: _display_name(binding.token))
        return tuple(
            {
                "module": _module_name(node.key),
                "token": _display_name(binding.token),
                "scope": binding.scope.value,
                "resolver": binding.resolver_kind,
                "exported": binding.token in node.exported_providers,
            }
            for binding in bindings
        )

    def routes(self) -> tuple[dict[str, object], ...]:
        """Return the compiled routes, or nothing when there is no HTTP runtime.

        A standalone application context serves no routes, so there are none to report
        rather than an error to raise.
        """
        application = self._application.http_application
        if application is None:
            return ()
        return application.snapshot_routes()


@Module(providers=[DiscoveryService, ModuleRef], exports=[DiscoveryService, ModuleRef])
class DiscoveryModule:
    """Addon module that exposes the read-only DiscoveryService."""

    pass


def _module_name(key: ModuleKey) -> str:
    """Return the name one compiled module is reported under.

    A module built by a factory is reported as built, and by which registration of its
    class it is, so that two registrations of one class are told apart by a reader who
    has only this row in front of them. What distinguishes them - the providers each was
    built with - is what a report of an application's shape must not print.
    """

    if isinstance(key, type):
        return _display_name(key)
    return f"{_display_name(key.module)} (dynamic)[{key.instance_id}]"


def _resolve_module_node(
    nodes: tuple[object, ...],
    module: ModuleKey | type[object],
):
    for node in nodes:
        if getattr(node, "key", None) == module or getattr(node, "module", None) is module:
            return node
    raise KeyError(f"Unknown module {module!r}")
