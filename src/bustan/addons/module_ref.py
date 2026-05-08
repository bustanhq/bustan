"""Public provider lookup helper for one application module context."""

from __future__ import annotations

from typing import Annotated

from starlette.applications import Starlette

from ..app.application import Application
from ..common.decorators.injectable import Inject, Injectable
from ..common.types import ProviderScope
from ..core.ioc.tokens import APPLICATION
from ..core.module.dynamic import ModuleKey


@Injectable(scope=ProviderScope.TRANSIENT)
class ModuleRef:
    """Resolve providers through the finalized public application semantics."""

    def __init__(self, application: Annotated[object, Inject(APPLICATION)]) -> None:
        self._application = _resolve_application(application)
        self._module_key = self._application.root_key

    @property
    def module_key(self) -> ModuleKey:
        return self._module_key

    def for_module(self, module: ModuleKey | type[object]) -> ModuleRef:
        scoped = ModuleRef(self._application)
        scoped._module_key = _resolve_module_key(self._application, module)
        return scoped

    def get(self, token: object, *, strict: bool = True) -> object:
        module_key = self._module_key if strict else self._application.root_key
        return self._application.container.resolve(token, module=module_key)

    def resolve(self, token: object, *, strict: bool = True) -> object:
        return self.get(token, strict=strict)

    def create(self, cls: type[object]) -> object:
        return self._application.container.instantiate_class(cls, module=self._module_key)


def _resolve_application(application: object) -> Application:
    if isinstance(application, Application):
        return application
    if isinstance(application, Starlette):
        runtime = getattr(application.state, "bustan_application", None)
        if isinstance(runtime, Application):
            return runtime
    raise TypeError("ModuleRef requires an Application runtime")


def _resolve_module_key(application: Application, module: ModuleKey | type[object]) -> ModuleKey:
    for node in application.module_graph.nodes:
        if node.key == module or node.module is module:
            return node.key
    raise KeyError(f"Unknown module {module!r}")