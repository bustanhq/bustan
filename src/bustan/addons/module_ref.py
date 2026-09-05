"""Public provider lookup helper for one application module context."""

from __future__ import annotations

from typing import Annotated

from ..app.application import ApplicationContext
from ..common.decorators.injectable import Inject, Injectable
from ..common.types import ProviderScope
from ..contracts import HttpRequest
from ..core.errors import ProviderResolutionError
from ..core.ioc.tokens import APPLICATION
from ..core.module.dynamic import ModuleKey


@Injectable(scope=ProviderScope.TRANSIENT)
class ModuleRef:
    """Resolve providers through the finalized public application semantics."""

    def __init__(self, application: Annotated[object, Inject(APPLICATION)]) -> None:
        self._application = _resolve_application(application)
        self._module_key = self._application.root_key

    @classmethod
    def _from_application(
        cls,
        application: ApplicationContext,
        *,
        module_key: ModuleKey | None = None,
    ) -> ModuleRef:
        scoped = cls.__new__(cls)
        scoped._application = application
        scoped._module_key = application.root_key if module_key is None else module_key
        return scoped

    @property
    def module_key(self) -> ModuleKey:
        return self._module_key

    def for_module(self, module: ModuleKey | type[object]) -> ModuleRef:
        return self._from_application(
            self._application,
            module_key=_resolve_module_key(self._application, module),
        )

    def get(self, token: object, *, strict: bool = True) -> object:
        """Resolve a provider, against the request being served when there is one.

        This is the request-aware entry point: called from inside a handler, a guard or
        an interceptor it reaches request-scoped providers and returns the same instance
        the rest of that request sees. Called with no request in flight it resolves as
        `ApplicationContext.get` does, and a request-scoped provider is refused.

        `strict` keeps the lookup inside the module this reference names; pass `False`
        to fall back to what the root module can see.
        """
        module_key = self._module_key if strict else self._application.root_key
        return self._application.container.resolve(
            token, module=module_key, request=self._active_request()
        )

    def resolve(self, token: object, *, strict: bool = True) -> object:
        """Alias for `get()`, with the same request-aware semantics."""
        return self.get(token, strict=strict)

    def create(self, cls: type[object]) -> object:
        """Build one fresh instance of a class, against the request being served."""
        return self._application.container.instantiate_class(
            cls, module=self._module_key, request=self._active_request()
        )

    def _active_request(self) -> HttpRequest | None:
        """Return the request currently being served, or ``None`` outside one."""

        return self._application.container.scope_manager.active_request.get()


def _resolve_application(application: object) -> ApplicationContext:
    """Return the application context behind whatever ``APPLICATION`` resolved to."""

    if isinstance(application, ApplicationContext):
        return application
    # A server object carries the application it serves on its own state namespace,
    # which is how one is recognised without knowing whose server it is.
    runtime = getattr(getattr(application, "state", None), "bustan_application", None)
    if isinstance(runtime, ApplicationContext):
        return runtime
    raise ProviderResolutionError(
        "ModuleRef requires an application context; APPLICATION resolved to "
        f"{type(application).__name__}"
    )


def _resolve_module_key(
    application: ApplicationContext, module: ModuleKey | type[object]
) -> ModuleKey:
    for node in application.module_graph.nodes:
        if node.key == module or node.module is module:
            return node.key
    raise KeyError(f"Unknown module {module!r}")
