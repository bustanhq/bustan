"""Provider override management for testing and runtime composition."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from ...common.types import ProviderScope
from ..errors import ProviderResolutionError
from ..module.dynamic import ModuleInstanceKey, ModuleKey
from ..utils import _display_name, _qualname
from .planning.plan import ProvidedToken
from .registry import Registry, TokenKey, TokenMap, token_identity

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, MutableMapping

    from .planning.plan import ContainerPlan
    from .registry import Binding
    from .scopes import ScopeManager

__all__ = ["OverrideManager"]

# One binding, named the way every table in the container names it: the module that
# declares the token, paired with the token's type-aware identity.
type BindingIdentity = tuple[ModuleKey, TokenKey]


class OverrideManager:
    """Manages replacement objects for registered providers.

    An override is keyed by the module that declares the token and by the token's own
    identity, so overriding a token never reaches a different token that merely compares
    equal to it, such as the bare string a string enum member equals.

    An override belongs to bootstrap. It does not stand beside the provider it replaces;
    it replaces it for the whole application, which means dropping every instance already
    built from that provider or from anything that holds it. That is safe only while no
    request is in flight, so the window for registering one closes when the application
    reports that it has started, and every later attempt is refused rather than half
    honoured.
    """

    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self._overrides: dict[BindingIdentity, object] = {}
        self._started = False

    @property
    def started(self) -> bool:
        """Report whether the window in which overrides may be registered has closed."""

        return self._started

    def mark_started(self) -> None:
        """Report that startup has run, closing the window for registering overrides."""

        self._started = True

    def mark_stopped(self) -> None:
        """Report that shutdown has run, reopening the window.

        A stopped application has emptied every cache, so the next startup begins a new
        bootstrap and the overrides it is given are the ones it builds from.
        """

        self._started = False

    def override(
        self,
        token: object,
        value: object,
        *,
        module: ModuleKey | None = None,
        plan: ContainerPlan,
        scopes: ScopeManager,
    ) -> None:
        """Register a replacement object for a provider and make it reach every consumer.

        ``module`` names the module declaring the provider, and is needed only when more
        than one declares the token. A module class also names every dynamic registration
        of it, so a provider declared by a dynamic module is targeted by writing the class.

        Whatever the container has already built from the binding, or from a binding that
        transitively depends on it, is dropped, so the next resolution builds it against
        the replacement instead of the provider. A replacement for a singleton binding
        becomes that singleton, because the lifecycle runs its hooks over the instances
        the container holds and a replacement held nowhere would be initialized by nobody.
        """

        self._refuse_after_startup(token)
        binding = self._binding_identity(token, module)
        self._overrides[binding] = value
        _evict_reach(binding, registry=self.registry, plan=plan, scopes=scopes)
        _seat_singleton(binding, value, registry=self.registry, scopes=scopes)

    def clear_override(
        self,
        token: object,
        *,
        module: ModuleKey | None = None,
        plan: ContainerPlan,
        scopes: ScopeManager,
    ) -> None:
        """Remove any override registered for a provider and undo everything it reached.

        Every instance built while the replacement stood is dropped with it, so a
        singleton first built against a replacement does not outlive the override.
        """

        self._refuse_after_startup(token)
        binding = self._binding_identity(token, module)
        self._overrides.pop(binding, None)
        _evict_reach(binding, registry=self.registry, plan=plan, scopes=scopes)

    def has_override(self, token: object, *, module: ModuleKey | None = None) -> bool:
        """Report whether a replacement object is registered for a provider."""

        try:
            return self._binding_identity(token, module) in self._overrides
        except ProviderResolutionError:
            return False

    def get_override(self, token: object, *, module: ModuleKey | None = None) -> object | None:
        """Return the replacement object registered for a provider, if there is one."""

        try:
            return self._overrides.get(self._binding_identity(token, module))
        except ProviderResolutionError:
            return None

    def _refuse_after_startup(self, token: object) -> None:
        """Refuse an override the application is already too far along to honour."""

        if not self._started:
            return
        raise ProviderResolutionError(
            f"{_qualname(token)} cannot be overridden while the application is running. "
            "An override replaces a provider for the whole application, including the "
            "instances built from it, so every override must be registered before startup"
        )

    def _binding_identity(self, token: object, module: ModuleKey | None) -> BindingIdentity:
        """Return the one binding an override names, refusing anything else.

        The token is matched by its identity rather than by equality alone, so a token
        equal to a declared one but of another type is an unregistered token here, not a
        second way to spell the one that is registered.
        """

        identity = token_identity(token)
        declaring = [
            registered_module
            for registered_module, registered_token in self.registry.bindings
            if token_identity(registered_token) == identity
        ]

        if module is None:
            return (self._exactly_one(declaring, token, None), identity)

        matched = [candidate for candidate in declaring if _names_module(candidate, module)]
        return (self._exactly_one(matched, token, module), identity)

    def _exactly_one(
        self, declaring: list[ModuleKey], token: object, module: ModuleKey | None
    ) -> ModuleKey:
        """Return the single module that declares a token, or say why there is not one."""

        if len(declaring) == 1:
            return declaring[0]

        if not declaring:
            where = "the container" if module is None else _display_name(module)
            raise ProviderResolutionError(f"{_display_name(token)} is not registered in {where}")

        modules = ", ".join(_display_name(candidate) for candidate in declaring)
        raise ProviderResolutionError(
            f"{_display_name(token)} is registered in more than one module ({modules}); "
            "name the one to override it in as 'module'"
        )


def _names_module(candidate: ModuleKey, module: ModuleKey) -> bool:
    """Report whether a module key is the one an override was aimed at.

    A dynamic registration has an identity of its own, which callers outside the
    container never hold, so the class it registers names every registration of it and
    only two registrations of the same class declaring the same token are ambiguous.
    """

    if candidate == module:
        return True
    return isinstance(candidate, ModuleInstanceKey) and candidate.module is module


def _seat_singleton(
    binding_identity: BindingIdentity,
    value: object,
    *,
    registry: Registry,
    scopes: ScopeManager,
) -> None:
    """Cache a replacement as the singleton it stands in for, when the binding has one."""

    module_key, (_token_type, token) = binding_identity
    binding = registry.get_binding((module_key, token))
    if binding is not None and binding.scope is ProviderScope.SINGLETON:
        scopes.set_singleton((module_key, token), value)


def _evict_reach(
    binding_identity: BindingIdentity,
    *,
    registry: Registry,
    plan: ContainerPlan,
    scopes: ScopeManager,
) -> None:
    """Drop every cached instance that one binding's replacement invalidates.

    Request caches are not reached, and do not need to be: they exist only while a
    request is being served, which is after the last point an override may be registered.
    """

    invalidated = _binding_with_dependents(binding_identity, registry, plan)
    _drop_cached(scopes.singletons, invalidated)
    _drop_cached(scopes.durable_instances, invalidated)
    # Every controller is built from the graph the override just changed, and a
    # controller is cheap to rebuild, so they go rather than being traced one by one.
    scopes.clear_controller_singletons()


def _drop_cached[KeyT](
    cache: MutableMapping[KeyT, object], invalidated: frozenset[BindingIdentity]
) -> None:
    """Forget every entry in one instance cache that an invalidated binding built.

    Both caches key their entries by the declaring module and the token first, so the
    same two leading fields identify the binding whichever cache is being swept.
    """

    for key in tuple(cache):
        module_key, token = cast("tuple[ModuleKey, object]", key)[:2]
        if (module_key, token_identity(token)) in invalidated:
            del cache[key]


def _binding_with_dependents(
    binding_identity: BindingIdentity, registry: Registry, plan: ContainerPlan
) -> frozenset[BindingIdentity]:
    """Return a binding together with every binding that reaches it, however indirectly."""

    dependents = _dependents_index(registry, plan)
    reached = {binding_identity}
    pending = [binding_identity]
    while pending:
        holders = dependents.get(pending.pop(), set())
        for holder in holders - reached:
            reached.add(holder)
            pending.append(holder)
    return frozenset(reached)


def _dependents_index(
    registry: Registry, plan: ContainerPlan
) -> dict[BindingIdentity, set[BindingIdentity]]:
    """Map each binding to the bindings that hold it directly.

    The index is built when an override is registered rather than kept up to date,
    because an override is a bootstrap-time act and the table it reads never changes
    after the graph is built.
    """

    index: dict[BindingIdentity, set[BindingIdentity]] = {}
    for module_key, token in registry.bindings:
        binding = registry.bindings[(module_key, token)]
        holder = (module_key, token_identity(token))
        for needed in _needs(binding, module_key, registry, plan):
            index.setdefault(needed, set()).add(holder)
    return index


def _needs(
    binding: Binding, module_key: ModuleKey, registry: Registry, plan: ContainerPlan
) -> Iterator[BindingIdentity]:
    """Yield the binding behind each token one binding has to resolve to be built."""

    for token in _needed_tokens(binding, module_key, plan):
        declaring = _declaring_module(token, module_key, registry)
        if declaring is not None:
            yield (declaring, token_identity(token))


def _needed_tokens(
    binding: Binding, module_key: ModuleKey, plan: ContainerPlan
) -> tuple[object, ...]:
    """Return the tokens one binding resolves, whichever kind of binding it is."""

    if binding.resolver_kind == "class" and isinstance(binding.target, type):
        construction = plan.for_target(module_key, binding.target)
        if construction is None:
            return ()
        return tuple(
            argument.source.token
            for argument in construction.arguments
            if isinstance(argument.source, ProvidedToken)
        )
    if binding.resolver_kind == "factory":
        _factory, inject = cast("tuple[Callable[..., object], tuple[object, ...]]", binding.target)
        return inject
    if binding.resolver_kind == "existing":
        return (binding.target,)
    return ()


def _declaring_module(token: object, module_key: ModuleKey, registry: Registry) -> ModuleKey | None:
    """Return the module a token resolves to from one module, or ``None`` for no binding.

    A token the container answers itself, such as the request being served, is declared
    by no module and reaches no binding, so it has nothing an override could invalidate.
    """

    visible = registry.module_visibility.get(module_key, TokenMap[ModuleKey]())
    try:
        return visible.get(token)
    except TypeError:
        # A token nothing can hash was never a key in a visibility table. A factory may
        # still name one in its inject list, and reading the graph must not be what
        # turns that mistake into a crash somewhere else entirely.
        return None
