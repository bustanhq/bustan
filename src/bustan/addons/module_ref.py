"""Public provider lookup helper for one application module context."""

from __future__ import annotations

from typing import Annotated

from ..app.application import ApplicationContext
from ..common.decorators.injectable import Inject, Injectable
from ..common.tokens import token_identity
from ..common.types import ProviderScope
from ..contracts import HttpRequest
from ..kernel.errors import ProviderResolutionError
from ..kernel.ioc.tokens import APPLICATION
from ..kernel.module.dynamic import ModuleKey
from ..kernel.utils import _display_name, _qualname


@Injectable(scope=ProviderScope.TRANSIENT)
class ModuleRef:
    """Resolve providers through the finalized public application semantics."""

    def __init__(self, application: Annotated[ApplicationContext, Inject(APPLICATION)]) -> None:
        self._application = _application_context(application, "ModuleRef")
        self._module_key = _host_module_key(self._application)

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
        """The module this reference resolves against.

        A reference injected into a provider or a controller names the module that
        class was declared in, so it sees exactly what the class's own constructor
        sees. One asked of the application itself names the root module.
        """
        return self._module_key

    def for_module(self, module: ModuleKey | type[object]) -> ModuleRef:
        """Return a reference that resolves against another module of this application."""
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

        `strict` keeps the lookup inside the module this reference names, which is the
        module the class holding the reference was declared in. Pass `False` to widen a
        token that module cannot see into a search of every module in the application,
        so a provider another module declares privately is still reachable. The search
        refuses to guess: a token more than one module declares raises rather than
        picking one, and `for_module()` names the one to resolve through.
        """
        module_key = self._module_key if strict else self._search_module(token)
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

    def _search_module(self, token: object) -> ModuleKey:
        """Return the module a non-strict lookup resolves a token through.

        What this reference's own module can see is that module's answer, so the search
        starts only where that module can see nothing under the token at all.
        """

        if _is_visible_to(self._application, self._module_key, token):
            return self._module_key

        declaring = _modules_declaring(self._application, token)
        if len(declaring) == 1:
            return declaring[0]
        if len(declaring) > 1:
            named = ", ".join(_display_name(module) for module in declaring)
            raise ProviderResolutionError(
                f"{_qualname(token)} is declared by more than one module ({named}), so a "
                f"non-strict lookup from {_display_name(self._module_key)} has no single "
                "provider to return. Name the module to resolve through with 'for_module'"
            )
        # No module declares it, so the module this reference names reports it missing
        # in the same words a strict lookup would.
        return self._module_key


def _host_module_key(application: ApplicationContext) -> ModuleKey:
    """Return the module whose construction asked for a reference.

    A reference is transient, so one is built per consumer and belongs to the module
    that consumer was declared in. That is the module the consumer's own constructor
    already resolves against, and answering a lookup through a different module would
    make the reference see more, or less, than the class holding it. A reference
    nothing is being built for - one asked of the application directly - belongs to the
    root module, which is what the application itself resolves against.
    """

    container = application.container
    frames = container.kernel.resolution_stack.get()
    # The reference's own binding is the innermost frame, so the binding that asked for
    # it is the one below.
    if len(frames) >= 2:
        return frames[-2].module

    # A controller is built without a binding of its own, so nothing named its module
    # on the resolution stack and the class being built names it instead.
    building = container.kernel.construction_stack.get()
    if len(building) >= 2:
        host = container.registry.controller_module_view.get(building[-2])
        if host is not None:
            return host
    return application.root_key


def _is_visible_to(application: ApplicationContext, module_key: ModuleKey, token: object) -> bool:
    """Report whether one module resolves a token through its own providers or imports."""

    visibility = application.container.registry.visibility_view.get(module_key)
    return visibility is not None and token in visibility


def _modules_declaring(application: ApplicationContext, token: object) -> tuple[ModuleKey, ...]:
    """Return every module declaring a provider for a token, in registration order."""

    identity = token_identity(token)
    return tuple(
        module_key
        for module_key, bound_token in application.container.registry.binding_view
        if token_identity(bound_token) == identity
    )


def _application_context(application: object, requested_by: str) -> ApplicationContext:
    """Narrow what ``APPLICATION`` answered with to an application context.

    Every application seats its context on the container it was built for, so this
    refuses only a container that was told it belongs to something else entirely.
    """

    if isinstance(application, ApplicationContext):
        return application
    raise ProviderResolutionError(
        f"{requested_by} needs the application context, and this container was told it belongs "
        f"to {type(application).__name__} instead"
    )


def _resolve_module_key(
    application: ApplicationContext, module: ModuleKey | type[object]
) -> ModuleKey:
    for node in application.module_graph.nodes:
        if node.key == module or node.module is module:
            return node.key
    raise KeyError(f"Unknown module {module!r}")
