"""Effective scope algebra over the dependency injection binding table.

Every instance the container caches is cached over some context: a singleton over
the whole process, a durable provider over its partition, a request-scoped
provider over one request, a transient over nothing at all. An owner may hold a
dependency only when that dependency's state lives at least as long as the owner
does. Holding shorter-lived state keeps the first caller's data alive past that
caller and serves it to the next.

The rule follows the whole chain, not the first hop. A binding that keeps no
instance of its own - a transient, or an alias to another token - constrains
nothing by itself and is judged by the narrowest scope reachable through it, so
neither can carry request-local state into a longer-lived owner. A factory is
judged by every token in its inject list.

The answer is computed once, from the table, before anything is built: the
caller passes the binding table, the per-module visibility map and the
constructor dependencies of every class the graph can build, and receives one
effective scope per binding plus every edge the rules refuse. A controller is
passed as a class binding under the scope it is cached at, so it is judged by the
same rules as a provider.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from ....common.types import ProviderScope
from ....contracts import HttpRequest, HttpResponse, names_native_request
from ...module.dynamic import ModuleKey
from ...utils import _qualname
from ..registry import Binding
from ..tokens import INQUIRER, REQUEST, RESPONSE

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping
    from contextvars import ContextVar

BindingKey = tuple[ModuleKey, object]

# How wide a context each scope caches over, narrowest first. TRANSIENT keeps no
# cache of its own, so it constrains nobody: it sorts widest, which makes it both
# the answer for a binding that reaches nothing and the identity of _narrowest.
_CACHE_WIDTH: dict[ProviderScope, int] = {
    ProviderScope.REQUEST: 0,
    ProviderScope.DURABLE: 1,
    ProviderScope.SINGLETON: 2,
    ProviderScope.TRANSIENT: 3,
}

# Tokens standing for state the server owns for one request, with the phrase an
# error uses to name each. They are compared by identity, because a dependency
# token is arbitrary and need not be hashable.
_REQUEST_DERIVED_TOKENS: tuple[tuple[object, str], ...] = (
    (HttpRequest, "framework-owned type HttpRequest"),
    (HttpResponse, "framework-owned type HttpResponse"),
    (REQUEST, "the REQUEST token"),
    (RESPONSE, "the RESPONSE token"),
)

# What an error calls a parameter that named its transport's own request type. That
# object lives for one request exactly as the contract wrapped around it does, so an
# owner outliving a request may not hold it under either spelling.
_NATIVE_REQUEST_DESCRIPTION = "the transport's own request object"


@dataclass(frozen=True, slots=True)
class ScopeDependency:
    """One token an owner asks for, and where it asked for it.

    ``site`` is read inside an error message and names the place the token was
    requested, for example ``parameter 'identity'``.
    """

    token: object
    site: str


@dataclass(frozen=True, slots=True)
class ScopeViolation:
    """One dependency an owner may not hold, with the error that reports it."""

    owner: BindingKey
    owner_scope: ProviderScope
    dependency: object
    reached_scope: ProviderScope | None
    message: str


@dataclass(frozen=True, slots=True)
class ScopePlan:
    """What every binding may hand over, and every edge the scope rules refuse.

    ``effective_scopes`` gives the narrowest scope each binding exposes to
    whoever holds it, keyed the same way as the binding table. ``violations`` is
    empty for a graph that obeys the rules and is ordered by binding declaration
    so that a report of a broken graph reads the same on every run.
    """

    effective_scopes: Mapping[BindingKey, ProviderScope]
    violations: tuple[ScopeViolation, ...]


def plan_scopes(
    bindings: Mapping[BindingKey, Binding],
    *,
    visibility: Mapping[ModuleKey, Mapping[object, ModuleKey]],
    class_dependencies: Mapping[type[object], tuple[ScopeDependency, ...]],
) -> ScopePlan:
    """Compute each binding's effective scope and collect every illegal edge.

    ``bindings`` is the binding table keyed by declaring module and token,
    ``visibility`` maps each module to the module declaring every token that
    module can see, and ``class_dependencies`` gives the tokens each class asks
    for in its constructor. A class absent from that mapping is taken to ask for
    nothing; a token no module can see constrains nothing, because a dependency
    the graph cannot resolve is reported where it is resolved rather than here.

    Nothing is raised. Every violation is returned so a caller can report a
    graph's failures together instead of one per attempt.
    """

    graph = _ScopeGraph(
        bindings=bindings,
        visibility=visibility,
        class_dependencies=class_dependencies,
    )
    effective_scopes = graph.solve()
    violations = graph.violations(effective_scopes)
    return ScopePlan(
        effective_scopes=MappingProxyType(effective_scopes),
        violations=violations,
    )


@contextmanager
def entered_request_scope(
    active_request: ContextVar[HttpRequest | None],
    request: HttpRequest | None,
) -> Iterator[None]:
    """Bind the request a resolution runs under, clearing it when there is none.

    An entry point that was handed no request must resolve as though no request
    were active. Leaving the variable untouched instead lets an imperative
    resolution inherit whichever request happens to be in flight further out, and
    a provider constructed that way captures one caller's state for as long as it
    is cached.
    """

    token = active_request.set(request)
    try:
        yield
    finally:
        active_request.reset(token)


@dataclass(frozen=True, slots=True)
class _ScopeGraph:
    """The binding table read as a graph of what each binding can hand over."""

    bindings: Mapping[BindingKey, Binding]
    visibility: Mapping[ModuleKey, Mapping[object, ModuleKey]]
    class_dependencies: Mapping[type[object], tuple[ScopeDependency, ...]]

    def solve(self) -> dict[BindingKey, ProviderScope]:
        """Return the narrowest scope every binding hands to whoever holds it.

        A binding with a cache of its own hands over exactly that cache's scope.
        The rest are recomputed until nothing changes. Each pass can only narrow a
        binding's answer and there are four scopes, so a table whose bindings
        reach each other in a cycle settles rather than recursing without end.
        """

        scopes = {
            key: ProviderScope.TRANSIENT if self.is_pass_through(binding) else binding.scope
            for key, binding in self.bindings.items()
        }
        pass_through = [
            (key, binding)
            for key, binding in self.bindings.items()
            if self.is_pass_through(binding)
        ]

        changed = True
        while changed:
            changed = False
            for key, binding in pass_through:
                reached = _narrowest(
                    self.reached_scope(dependency.token, key[0], scopes)
                    for dependency in self.dependencies(binding)
                )
                if reached is not scopes[key]:
                    scopes[key] = reached
                    changed = True
        return scopes

    def violations(self, scopes: Mapping[BindingKey, ProviderScope]) -> tuple[ScopeViolation, ...]:
        """Return every edge the scope rules refuse, in binding declaration order."""

        found: list[ScopeViolation] = []
        for key, binding in self.bindings.items():
            # A transient captures nothing of its own, so whatever it reaches is
            # charged to whichever owner holds it.
            if binding.scope is ProviderScope.TRANSIENT:
                continue
            owner_label = self.owner_label(binding)
            for dependency in self.dependencies(binding):
                violation = self._violation(key, binding, owner_label, dependency, scopes)
                if violation is not None:
                    found.append(violation)
        return tuple(found)

    def _violation(
        self,
        key: BindingKey,
        binding: Binding,
        owner_label: str,
        dependency: ScopeDependency,
        scopes: Mapping[BindingKey, ProviderScope],
    ) -> ScopeViolation | None:
        """Return the violation one dependency of one owner raises, if any."""

        if dependency.token is INQUIRER:
            return ScopeViolation(
                owner=key,
                owner_scope=binding.scope,
                dependency=INQUIRER,
                reached_scope=None,
                message=_inquirer_message(owner_label, dependency.site, binding.scope),
            )

        reached = self.reached_scope(dependency.token, key[0], scopes)
        if not _escapes_owner(binding.scope, reached):
            return None
        return ScopeViolation(
            owner=key,
            owner_scope=binding.scope,
            dependency=dependency.token,
            reached_scope=reached,
            message=_scope_message(
                owner_label=owner_label,
                site=dependency.site,
                token=dependency.token,
                owner_scope=binding.scope,
                reached=reached,
                witness=self.witness(dependency.token, key[0], reached),
            ),
        )

    def reached_scope(
        self,
        token: object,
        module: ModuleKey,
        scopes: Mapping[BindingKey, ProviderScope],
    ) -> ProviderScope:
        """Return the narrowest scope a token hands to whoever asks for it."""

        if _is_request_derived(token):
            return ProviderScope.REQUEST
        located = self.locate(token, module)
        if located is None:
            return ProviderScope.TRANSIENT
        return scopes[located[0]]

    def witness(
        self,
        token: object,
        module: ModuleKey,
        reached: ProviderScope,
        seen: tuple[BindingKey, ...] = (),
    ) -> object | None:
        """Return the token whose own lifetime is why a dependency reaches a scope.

        The walk stops at a binding already on the path, so a cyclic table names
        no witness rather than following the cycle.
        """

        if _is_request_derived(token):
            return token if reached is ProviderScope.REQUEST else None
        located = self.locate(token, module)
        if located is None:
            return None
        key, binding = located
        if key in seen:
            return None
        if not self.is_pass_through(binding):
            return token if binding.scope is reached else None
        for dependency in self.dependencies(binding):
            found = self.witness(dependency.token, key[0], reached, (*seen, key))
            if found is not None:
                return found
        return None

    def locate(self, token: object, module: ModuleKey) -> tuple[BindingKey, Binding] | None:
        """Return a token's binding and the key it is registered under, if any."""

        try:
            declaring_module = self.visibility.get(module, {}).get(token)
        except TypeError:
            # An unhashable annotation cannot be a provider token.
            return None
        if declaring_module is None:
            return None
        key = (declaring_module, token)
        binding = self.bindings.get(key)
        if binding is None:
            return None
        return key, binding

    def dependencies(self, binding: Binding) -> tuple[ScopeDependency, ...]:
        """Return the tokens a binding asks the container for."""

        if binding.resolver_kind == "existing":
            return (ScopeDependency(token=binding.target, site="alias target"),)
        if binding.resolver_kind == "factory":
            _factory, inject = cast(tuple[object, tuple[object, ...]], binding.target)
            return tuple(ScopeDependency(token=token, site="inject entry") for token in inject)
        if binding.resolver_kind == "class" and isinstance(binding.target, type):
            return tuple(self.class_dependencies.get(binding.target, ()))
        return ()

    def is_pass_through(self, binding: Binding) -> bool:
        """Return whether a binding keeps no instance of its own."""

        return binding.resolver_kind == "existing" or binding.scope is ProviderScope.TRANSIENT

    def owner_label(self, binding: Binding) -> str:
        """Return the phrase an error uses to name whoever holds a dependency."""

        if binding.resolver_kind == "factory":
            factory, _inject = cast(tuple[object, tuple[object, ...]], binding.target)
            return f"Factory {_factory_label(factory)}"
        if binding.resolver_kind == "class" and isinstance(binding.target, type):
            return f"{_qualname(binding.target)}.__init__"
        return _qualname(binding.token)


def _request_description(token: object) -> str | None:
    """Return the phrase naming a request-derived token, or None for anything else."""

    for derived, description in _REQUEST_DERIVED_TOKENS:
        if token is derived:
            return description
    if names_native_request(token):
        return _NATIVE_REQUEST_DESCRIPTION
    return None


def _is_request_derived(token: object) -> bool:
    """Return whether a token stands for state that lives for one request only."""

    return _request_description(token) is not None


def _escapes_owner(owner_scope: ProviderScope, reached: ProviderScope) -> bool:
    """Return whether an owner would outlive state it is about to hold.

    A transient owner caches nothing and a transient dependency exposes nothing
    of its own, so neither is unsafe in itself.
    """

    if owner_scope is ProviderScope.TRANSIENT or reached is ProviderScope.TRANSIENT:
        return False
    return _CACHE_WIDTH[owner_scope] > _CACHE_WIDTH[reached]


def _narrowest(scopes: Iterable[ProviderScope]) -> ProviderScope:
    """Return the scope caching over the narrowest context, TRANSIENT when none."""

    return min(scopes, key=_CACHE_WIDTH.__getitem__, default=ProviderScope.TRANSIENT)


def _factory_label(factory: object) -> str:
    """Return a stable name for a factory to use in a diagnostic."""

    qualname = getattr(factory, "__qualname__", None)
    if qualname is None:
        return _qualname(factory)
    module = getattr(factory, "__module__", None)
    return f"{module}.{qualname}" if module else str(qualname)


def _reached_description(reached: ProviderScope, witness: object | None) -> str:
    """Return the phrase naming the state a dependency reaches past itself."""

    if witness is None:
        return f"{reached.value}-scoped state"
    request_description = _request_description(witness)
    if request_description is not None:
        return request_description
    return f"{reached.value}-scoped provider {_qualname(witness)}"


def _scope_message(
    *,
    owner_label: str,
    site: str,
    token: object,
    owner_scope: ProviderScope,
    reached: ProviderScope,
    witness: object | None,
) -> str:
    """Return the error for an owner that would outlive the state it holds."""

    request_description = _request_description(token)
    if request_description is not None:
        return (
            f"{owner_label} {site} requests {request_description}, which can only be injected "
            f"into a request-scoped or transient owner. A {owner_scope.value}-scoped owner "
            "outlives the request and would serve the first caller's request to every later "
            "caller"
        )
    if witness is token:
        return (
            f"{owner_label} {site} depends on {reached.value}-scoped provider {_qualname(token)}, "
            "which can only be injected into an owner that lives no longer than it does. A "
            f"{owner_scope.value}-scoped owner outlives it and would share one caller's instance "
            "with every later caller"
        )
    return (
        f"{owner_label} {site} depends on {_qualname(token)}, which keeps no instance of its own "
        f"and reaches {_reached_description(reached, witness)}. It can only be injected into an "
        f"owner that lives no longer than that, and a {owner_scope.value}-scoped owner would "
        "capture one caller's state the first time it is built and serve it to every later caller"
    )


def _inquirer_message(owner_label: str, site: str, owner_scope: ProviderScope) -> str:
    """Return the error for INQUIRER asked for by a provider that is cached."""

    return (
        f"{owner_label} {site} requests INQUIRER, which can only be injected into a transient "
        f"provider. A {owner_scope.value}-scoped provider is built once and reused, so it would "
        "record whichever consumer resolved it first and report that same consumer to every "
        "later one"
    )
