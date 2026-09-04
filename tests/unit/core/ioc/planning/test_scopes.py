"""Unit tests for the effective scope algebra over a binding table.

The value of these tests is the completeness of the matrix: every owner scope is
crossed with every shape a dependency can take, and each crossing asserts both
the effective scope the algebra computes and, where the edge is illegal, the
message it reports.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, cast

import pytest
from starlette.requests import Request
from starlette.responses import Response

from bustan.common.types import ProviderScope
from bustan.core.ioc.planning.scopes import (
    ScopeDependency,
    ScopePlan,
    entered_request_scope,
    plan_scopes,
)
from bustan.core.ioc.registry import normalize_provider
from bustan.core.ioc.tokens import APPLICATION, INQUIRER, REQUEST, RESPONSE, InjectionToken

if TYPE_CHECKING:
    from bustan.core.ioc.registry import Binding
    from bustan.core.module.dynamic import ModuleKey


class AppModule:
    """The single module every fixture table registers its bindings in."""


class SingletonService:
    """A provider that depends on nothing and lives for the whole process."""


class DurableTenant:
    """A provider cached per partition."""

    @classmethod
    def get_durable_context_key(cls, request: Request | None) -> str:
        return request.headers.get("x-tenant", "none") if request is not None else "none"


class RequestIdentity:
    """A provider cached for one request, built from that request."""


class TransientProbe:
    """A provider that keeps no instance and reaches nothing."""


class TransientBridge:
    """A provider that keeps no instance but reaches request-scoped state."""


class Owner:
    """The class every owner-scope binding in the matrix is built from."""

    @classmethod
    def get_durable_context_key(cls, request: Request | None) -> str:
        return "none"


def make_snapshot(identity: RequestIdentity) -> dict[str, str]:
    """Stand in for a user factory that reads request-scoped state."""

    return {"identity": repr(identity)}


ALIAS_TO_REQUEST = InjectionToken("ALIAS_TO_REQUEST")
ALIAS_TO_ALIAS = InjectionToken("ALIAS_TO_ALIAS")
ALIAS_TO_SINGLETON = InjectionToken("ALIAS_TO_SINGLETON")
CONFIG_VALUE = InjectionToken("CONFIG_VALUE")
REQUEST_FACTORY = InjectionToken("REQUEST_FACTORY")
UNBOUND = InjectionToken("UNBOUND")

OWNER_TOKEN = InjectionToken("OWNER")
OWNER_SITE = "parameter 'dependency'"

# The whole point of the exercise, written out rather than computed: an owner may
# hold state that lives at least as long as it does, and nothing shorter. A
# transient owner caches nothing and a transient dependency exposes nothing of its
# own, so neither constrains the other.
REJECTING_OWNERS: dict[ProviderScope, frozenset[ProviderScope]] = {
    ProviderScope.REQUEST: frozenset({ProviderScope.SINGLETON, ProviderScope.DURABLE}),
    ProviderScope.DURABLE: frozenset({ProviderScope.SINGLETON}),
    ProviderScope.SINGLETON: frozenset(),
    ProviderScope.TRANSIENT: frozenset(),
}

BASE_PROVIDERS: tuple[dict[str, object], ...] = (
    {"provide": SingletonService, "use_class": SingletonService, "scope": "singleton"},
    {"provide": DurableTenant, "use_class": DurableTenant, "scope": "durable"},
    {"provide": RequestIdentity, "use_class": RequestIdentity, "scope": "request"},
    {"provide": TransientProbe, "use_class": TransientProbe, "scope": "transient"},
    {"provide": TransientBridge, "use_class": TransientBridge, "scope": "transient"},
    {"provide": ALIAS_TO_REQUEST, "use_existing": RequestIdentity},
    {"provide": ALIAS_TO_ALIAS, "use_existing": ALIAS_TO_REQUEST},
    {"provide": ALIAS_TO_SINGLETON, "use_existing": SingletonService},
    {"provide": CONFIG_VALUE, "use_value": {"retries": 3}},
    {
        "provide": REQUEST_FACTORY,
        "use_factory": make_snapshot,
        "inject": [RequestIdentity],
        "scope": "request",
    },
)

# TransientBridge is the one fixture class with a dependency of its own.
BASE_CLASS_DEPENDENCIES: dict[type[object], tuple[ScopeDependency, ...]] = {
    TransientBridge: (ScopeDependency(token=RequestIdentity, site="parameter 'identity'"),),
}


def build_table(
    declarations: tuple[dict[str, object], ...],
    *,
    module: ModuleKey = AppModule,
) -> tuple[dict[tuple[ModuleKey, object], Binding], dict[ModuleKey, dict[object, ModuleKey]]]:
    """Register provider declarations the way a module does, and expose them all."""

    bindings: dict[tuple[ModuleKey, object], Binding] = {}
    for declaration in declarations:
        binding = normalize_provider(declaration, module)
        bindings[(module, binding.token)] = binding
    visibility: dict[ModuleKey, dict[object, ModuleKey]] = {
        module: {token: declaring for declaring, token in bindings}
    }
    return bindings, visibility


def plan(
    *declarations: dict[str, object],
    class_dependencies: dict[type[object], tuple[ScopeDependency, ...]] | None = None,
) -> ScopePlan:
    """Plan the scopes of the base table extended with the given declarations."""

    bindings, visibility = build_table((*BASE_PROVIDERS, *declarations))
    dependencies = {**BASE_CLASS_DEPENDENCIES, **(class_dependencies or {})}
    return plan_scopes(bindings, visibility=visibility, class_dependencies=dependencies)


def owner_declaration(scope: ProviderScope) -> dict[str, object]:
    """Return the declaration of the matrix owner at one scope."""

    return {"provide": OWNER_TOKEN, "use_class": Owner, "scope": scope.value}


def plan_owner(scope: ProviderScope, token: object) -> ScopePlan:
    """Plan a table whose only owner is at ``scope`` and asks for ``token``."""

    return plan(
        owner_declaration(scope),
        class_dependencies={Owner: (ScopeDependency(token=token, site=OWNER_SITE),)},
    )


@dataclass(frozen=True)
class DependencyShape:
    """One shape a dependency can take, and the scope it exposes to an owner.

    ``registered`` marks the shapes the base table declares a binding for; the
    rest are framework-owned annotations and tokens no module declares.
    """

    name: str
    token: object
    reached: ProviderScope
    registered: bool = True


DEPENDENCY_SHAPES: tuple[DependencyShape, ...] = (
    DependencyShape("singleton class", SingletonService, ProviderScope.SINGLETON),
    DependencyShape("durable class", DurableTenant, ProviderScope.DURABLE),
    DependencyShape("request class", RequestIdentity, ProviderScope.REQUEST),
    DependencyShape("transient reaching nothing", TransientProbe, ProviderScope.TRANSIENT),
    DependencyShape("transient reaching request", TransientBridge, ProviderScope.REQUEST),
    DependencyShape("alias to request class", ALIAS_TO_REQUEST, ProviderScope.REQUEST),
    DependencyShape("alias to alias to request class", ALIAS_TO_ALIAS, ProviderScope.REQUEST),
    DependencyShape("alias to singleton class", ALIAS_TO_SINGLETON, ProviderScope.SINGLETON),
    DependencyShape("value provider", CONFIG_VALUE, ProviderScope.SINGLETON),
    DependencyShape("request-scoped factory", REQUEST_FACTORY, ProviderScope.REQUEST),
    DependencyShape("starlette request", Request, ProviderScope.REQUEST, registered=False),
    DependencyShape("starlette response", Response, ProviderScope.REQUEST, registered=False),
    DependencyShape("request token", REQUEST, ProviderScope.REQUEST, registered=False),
    DependencyShape("response token", RESPONSE, ProviderScope.REQUEST, registered=False),
    DependencyShape("unbound token", UNBOUND, ProviderScope.TRANSIENT, registered=False),
    DependencyShape("application token", APPLICATION, ProviderScope.TRANSIENT, registered=False),
)

SHAPE_IDS = tuple(shape.name for shape in DEPENDENCY_SHAPES)
REGISTERED_SHAPES = tuple(shape for shape in DEPENDENCY_SHAPES if shape.registered)
REGISTERED_SHAPE_IDS = tuple(shape.name for shape in REGISTERED_SHAPES)


@pytest.mark.parametrize("shape", REGISTERED_SHAPES, ids=REGISTERED_SHAPE_IDS)
def test_effective_scope_of_every_binding_shape(shape: DependencyShape) -> None:
    """Each binding exposes the narrowest scope reachable through it."""

    assert plan().effective_scopes[(AppModule, shape.token)] is shape.reached


@pytest.mark.parametrize("owner_scope", tuple(ProviderScope), ids=lambda scope: scope.value)
@pytest.mark.parametrize("shape", DEPENDENCY_SHAPES, ids=SHAPE_IDS)
def test_owner_scope_matrix(shape: DependencyShape, owner_scope: ProviderScope) -> None:
    """Every owner scope crossed with every dependency shape is judged once."""

    violations = plan_owner(owner_scope, shape.token).violations
    rejected = owner_scope in REJECTING_OWNERS[shape.reached]

    assert [violation.dependency for violation in violations] == ([shape.token] if rejected else [])
    if not rejected:
        return

    violation = violations[0]
    assert violation.owner == (AppModule, OWNER_TOKEN)
    assert violation.owner_scope is owner_scope
    assert violation.reached_scope is shape.reached
    assert violation.message.startswith(f"{qualified(Owner)}.__init__ {OWNER_SITE} ")
    assert "can only be injected" in violation.message


@pytest.mark.parametrize("shape", DEPENDENCY_SHAPES, ids=SHAPE_IDS)
def test_transient_owners_may_hold_anything(shape: DependencyShape) -> None:
    """A transient keeps no instance, so it captures nothing it is given."""

    assert plan_owner(ProviderScope.TRANSIENT, shape.token).violations == ()


def qualified(target: type[object]) -> str:
    """Return the name the algebra prints for a class."""

    return f"{target.__module__}.{target.__qualname__}"


def test_singleton_owner_of_a_request_class_reports_the_documented_error() -> None:
    """The direct edge names the provider, its scope and the rule it breaks."""

    violation = plan_owner(ProviderScope.SINGLETON, RequestIdentity).violations[0]

    assert violation.message == (
        f"{qualified(Owner)}.__init__ {OWNER_SITE} depends on request-scoped provider "
        f"{qualified(RequestIdentity)}, which can only be injected into an owner that lives no "
        "longer than it does. A singleton-scoped owner outlives it and would share one caller's "
        "instance with every later caller"
    )


def test_singleton_owner_of_an_alias_names_the_provider_behind_it() -> None:
    """An alias keeps no instance, so the error names what it re-resolves."""

    violation = plan_owner(ProviderScope.SINGLETON, ALIAS_TO_REQUEST).violations[0]

    assert violation.message == (
        f"{qualified(Owner)}.__init__ {OWNER_SITE} depends on {ALIAS_TO_REQUEST!r}, which keeps "
        f"no instance of its own and reaches request-scoped provider {qualified(RequestIdentity)}."
        " It can only be injected into an owner that lives no longer than that, and a "
        "singleton-scoped owner would capture one caller's state the first time it is built and "
        "serve it to every later caller"
    )


def test_singleton_factory_inject_list_is_checked_against_the_factory_scope() -> None:
    """A factory's inject list is judged by the scope its result is cached under."""

    violations = plan(
        {
            "provide": InjectionToken("SNAPSHOT"),
            "use_factory": make_snapshot,
            "inject": [RequestIdentity],
        }
    ).violations

    assert len(violations) == 1
    assert violations[0].message == (
        f"Factory {make_snapshot.__module__}.make_snapshot inject entry depends on request-scoped "
        f"provider {qualified(RequestIdentity)}, which can only be injected into an owner that "
        "lives no longer than it does. A singleton-scoped owner outlives it and would share one "
        "caller's instance with every later caller"
    )


def test_a_factory_may_inject_what_its_own_scope_already_allows() -> None:
    """A request-scoped factory injecting request-scoped state is legal."""

    assert plan().violations == ()


def test_singleton_owner_of_a_transient_that_holds_the_request() -> None:
    """A transient does not launder the request it was built from."""

    violation = plan_owner(ProviderScope.SINGLETON, TransientBridge).violations[0]

    assert violation.message == (
        f"{qualified(Owner)}.__init__ {OWNER_SITE} depends on {qualified(TransientBridge)}, which "
        "keeps no instance of its own and reaches request-scoped provider "
        f"{qualified(RequestIdentity)}. It can only be injected into an owner that lives no "
        "longer than that, and a singleton-scoped owner would capture one caller's state the "
        "first time it is built and serve it to every later caller"
    )


def test_durable_owner_of_a_request_class_is_refused() -> None:
    """A durable instance outlives the request whose state it would hold."""

    violation = plan_owner(ProviderScope.DURABLE, RequestIdentity).violations[0]

    assert violation.message == (
        f"{qualified(Owner)}.__init__ {OWNER_SITE} depends on request-scoped provider "
        f"{qualified(RequestIdentity)}, which can only be injected into an owner that lives no "
        "longer than it does. A durable-scoped owner outlives it and would share one caller's "
        "instance with every later caller"
    )


def test_singleton_owner_of_a_durable_class_is_refused() -> None:
    """A singleton would serve the first partition's instance to every other."""

    violation = plan_owner(ProviderScope.SINGLETON, DurableTenant).violations[0]

    assert violation.message == (
        f"{qualified(Owner)}.__init__ {OWNER_SITE} depends on durable-scoped provider "
        f"{qualified(DurableTenant)}, which can only be injected into an owner that lives no "
        "longer than it does. A singleton-scoped owner outlives it and would share one caller's "
        "instance with every later caller"
    )


@pytest.mark.parametrize(
    ("token", "description"),
    (
        (Request, "framework-owned type Request"),
        (Response, "framework-owned type Response"),
        (REQUEST, "the REQUEST token"),
        (RESPONSE, "the RESPONSE token"),
    ),
    ids=("request-type", "response-type", "request-token", "response-token"),
)
def test_request_derived_dependencies_name_themselves(token: object, description: str) -> None:
    """Request-owned state reads as itself rather than as a provider."""

    violation = plan_owner(ProviderScope.SINGLETON, token).violations[0]

    assert violation.message == (
        f"{qualified(Owner)}.__init__ {OWNER_SITE} requests {description}, which can only be "
        "injected into a request-scoped or transient owner. A singleton-scoped owner outlives "
        "the request and would serve the first caller's request to every later caller"
    )


def test_a_request_scoped_owner_may_hold_a_transient_that_holds_the_request() -> None:
    """A transient helper reading the request is legal under a request-scoped owner."""

    assert plan_owner(ProviderScope.REQUEST, TransientBridge).violations == ()
    assert plan_owner(ProviderScope.REQUEST, Request).violations == ()


@pytest.mark.parametrize(
    "owner_scope",
    (ProviderScope.SINGLETON, ProviderScope.DURABLE, ProviderScope.REQUEST),
    ids=lambda scope: scope.value,
)
def test_inquirer_is_refused_for_every_cached_owner(owner_scope: ProviderScope) -> None:
    """A cached provider records one consumer and would report it to all of them."""

    violations = plan_owner(owner_scope, INQUIRER).violations

    assert len(violations) == 1
    assert violations[0].reached_scope is None
    assert violations[0].message == (
        f"{qualified(Owner)}.__init__ {OWNER_SITE} requests INQUIRER, which can only be injected "
        f"into a transient provider. A {owner_scope.value}-scoped provider is built once and "
        "reused, so it would record whichever consumer resolved it first and report that same "
        "consumer to every later one"
    )


def test_inquirer_is_allowed_in_a_transient_provider() -> None:
    """A transient is built for one consumer, so it can name that consumer."""

    assert plan_owner(ProviderScope.TRANSIENT, INQUIRER).violations == ()


def test_a_cyclic_binding_table_settles_instead_of_recursing() -> None:
    """Two transients that reach each other terminate with no state reached."""

    class LeftProbe:
        pass

    class RightProbe:
        pass

    result = plan(
        {"provide": LeftProbe, "use_class": LeftProbe, "scope": "transient"},
        {"provide": RightProbe, "use_class": RightProbe, "scope": "transient"},
        class_dependencies={
            LeftProbe: (ScopeDependency(token=RightProbe, site="parameter 'right'"),),
            RightProbe: (ScopeDependency(token=LeftProbe, site="parameter 'left'"),),
        },
    )

    assert result.effective_scopes[(AppModule, LeftProbe)] is ProviderScope.TRANSIENT
    assert result.effective_scopes[(AppModule, RightProbe)] is ProviderScope.TRANSIENT
    assert result.violations == ()


def test_a_cycle_that_reaches_request_scope_is_still_reported() -> None:
    """Cutting the cycle must not lose the request-scoped state inside it."""

    class LeftProbe:
        pass

    class RightProbe:
        pass

    result = plan(
        {"provide": LeftProbe, "use_class": LeftProbe, "scope": "transient"},
        {"provide": RightProbe, "use_class": RightProbe, "scope": "transient"},
        owner_declaration(ProviderScope.SINGLETON),
        class_dependencies={
            LeftProbe: (ScopeDependency(token=RightProbe, site="parameter 'right'"),),
            RightProbe: (
                ScopeDependency(token=LeftProbe, site="parameter 'left'"),
                ScopeDependency(token=RequestIdentity, site="parameter 'identity'"),
            ),
            Owner: (ScopeDependency(token=LeftProbe, site=OWNER_SITE),),
        },
    )

    assert result.effective_scopes[(AppModule, LeftProbe)] is ProviderScope.REQUEST
    assert result.effective_scopes[(AppModule, RightProbe)] is ProviderScope.REQUEST
    assert [violation.dependency for violation in result.violations] == [LeftProbe]
    assert f"reaches request-scoped provider {qualified(RequestIdentity)}" in (
        result.violations[0].message
    )


def test_an_alias_cycle_terminates() -> None:
    """An alias pointing at an alias that points back names no scope at all."""

    first = InjectionToken("FIRST")
    second = InjectionToken("SECOND")

    result = plan(
        {"provide": first, "use_existing": second},
        {"provide": second, "use_existing": first},
    )

    assert result.effective_scopes[(AppModule, first)] is ProviderScope.TRANSIENT
    assert result.violations == ()


def test_a_cyclic_witness_walk_reports_the_scope_without_a_provider_name() -> None:
    """A scope reached only through a cycle is reported without naming a witness."""

    class Loop:
        pass

    result = plan(
        {"provide": Loop, "use_class": Loop, "scope": "transient"},
        owner_declaration(ProviderScope.SINGLETON),
        class_dependencies={
            Loop: (
                ScopeDependency(token=Loop, site="parameter 'self_reference'"),
                ScopeDependency(token=RequestIdentity, site="parameter 'identity'"),
            ),
            Owner: (ScopeDependency(token=Loop, site=OWNER_SITE),),
        },
    )

    assert result.effective_scopes[(AppModule, Loop)] is ProviderScope.REQUEST
    assert len(result.violations) == 1


def test_every_illegal_edge_of_one_graph_is_reported_together() -> None:
    """A caller reporting a broken graph gets all of its failures at once."""

    result = plan(
        {
            "provide": InjectionToken("SNAPSHOT"),
            "use_factory": make_snapshot,
            "inject": [RequestIdentity, DurableTenant],
        },
        owner_declaration(ProviderScope.SINGLETON),
        class_dependencies={
            Owner: (
                ScopeDependency(token=ALIAS_TO_REQUEST, site="parameter 'alias'"),
                ScopeDependency(token=SingletonService, site="parameter 'service'"),
                ScopeDependency(token=Request, site="parameter 'request'"),
            )
        },
    )

    assert [violation.dependency for violation in result.violations] == [
        RequestIdentity,
        DurableTenant,
        ALIAS_TO_REQUEST,
        Request,
    ]


def test_an_unhashable_annotation_is_not_a_token() -> None:
    """A dependency the visibility map cannot look up constrains nothing."""

    result = plan(
        owner_declaration(ProviderScope.SINGLETON),
        class_dependencies={
            Owner: (ScopeDependency(token=["not", "a", "token"], site=OWNER_SITE),)
        },
    )

    assert result.violations == ()


def test_a_class_the_caller_did_not_describe_asks_for_nothing() -> None:
    """The annotation engine owns constructor failures, not the scope algebra."""

    result = plan(owner_declaration(ProviderScope.SINGLETON), class_dependencies={})

    assert result.violations == ()
    assert result.effective_scopes[(AppModule, OWNER_TOKEN)] is ProviderScope.SINGLETON


def test_a_dependency_declared_in_another_module_is_invisible() -> None:
    """A token a module cannot see is not the module's to be judged against."""

    class OtherModule:
        pass

    bindings, visibility = build_table(
        ({"provide": RequestIdentity, "use_class": RequestIdentity, "scope": "request"},),
        module=OtherModule,
    )
    owner_bindings, owner_visibility = build_table((owner_declaration(ProviderScope.SINGLETON),))

    result = plan_scopes(
        {**bindings, **owner_bindings},
        visibility={**visibility, **owner_visibility},
        class_dependencies={Owner: (ScopeDependency(token=RequestIdentity, site=OWNER_SITE),)},
    )

    assert result.violations == ()


def test_the_planned_scope_table_cannot_be_written_to() -> None:
    """The table outlives the graph, so nothing may edit it after the fact."""

    effective_scopes = cast(
        "dict[tuple[ModuleKey, object], ProviderScope]", plan().effective_scopes
    )

    with pytest.raises(TypeError):
        effective_scopes[(AppModule, SingletonService)] = ProviderScope.REQUEST


def test_entered_request_scope_clears_an_outer_request() -> None:
    """An entry point given no request must not inherit the one in flight."""

    active_request: ContextVar[Request | None] = ContextVar("active_request", default=None)
    outer = Request({"type": "http", "method": "GET", "path": "/", "headers": []})

    with entered_request_scope(active_request, outer):
        assert active_request.get() is outer
        with entered_request_scope(active_request, None):
            assert active_request.get() is None
        assert active_request.get() is outer

    assert active_request.get() is None


def test_a_transient_holding_the_request_names_the_request_it_reaches() -> None:
    """The error names request-owned state as itself, one hop removed."""

    class RequestHelper:
        pass

    result = plan(
        {"provide": RequestHelper, "use_class": RequestHelper, "scope": "transient"},
        owner_declaration(ProviderScope.SINGLETON),
        class_dependencies={
            RequestHelper: (ScopeDependency(token=Request, site="parameter 'request'"),),
            Owner: (ScopeDependency(token=RequestHelper, site=OWNER_SITE),),
        },
    )

    assert result.effective_scopes[(AppModule, RequestHelper)] is ProviderScope.REQUEST
    assert result.violations[0].message == (
        f"{qualified(Owner)}.__init__ {OWNER_SITE} depends on {qualified(RequestHelper)}, which "
        "keeps no instance of its own and reaches framework-owned type Request. It can only be "
        "injected into an owner that lives no longer than that, and a singleton-scoped owner "
        "would capture one caller's state the first time it is built and serve it to every later "
        "caller"
    )


def test_a_transient_holding_the_request_is_legal_under_a_request_scoped_owner() -> None:
    """A transient helper reading the request is what request scope is for."""

    class RequestHelper:
        pass

    result = plan(
        {"provide": RequestHelper, "use_class": RequestHelper, "scope": "transient"},
        owner_declaration(ProviderScope.REQUEST),
        class_dependencies={
            RequestHelper: (ScopeDependency(token=Request, site="parameter 'request'"),),
            Owner: (ScopeDependency(token=RequestHelper, site=OWNER_SITE),),
        },
    )

    assert result.violations == ()


def test_a_factory_without_a_qualified_name_is_still_named() -> None:
    """A partially applied factory has no name of its own to print."""

    factory = partial(make_snapshot)
    violations = plan(
        {
            "provide": InjectionToken("PARTIAL"),
            "use_factory": factory,
            "inject": [RequestIdentity],
        }
    ).violations

    assert violations[0].message.startswith(f"Factory {factory!r} inject entry depends on ")


def test_a_pass_through_binding_may_reach_a_token_no_module_declares() -> None:
    """An unresolvable token on the way to request state does not hide it."""

    class Bridge:
        pass

    result = plan(
        {"provide": Bridge, "use_class": Bridge, "scope": "transient"},
        owner_declaration(ProviderScope.SINGLETON),
        class_dependencies={
            Bridge: (
                ScopeDependency(token=UNBOUND, site="parameter 'unbound'"),
                ScopeDependency(token=RequestIdentity, site="parameter 'identity'"),
            ),
            Owner: (ScopeDependency(token=Bridge, site=OWNER_SITE),),
        },
    )

    assert result.effective_scopes[(AppModule, Bridge)] is ProviderScope.REQUEST
    assert f"reaches request-scoped provider {qualified(RequestIdentity)}" in (
        result.violations[0].message
    )


def test_a_visible_token_with_no_binding_constrains_nothing() -> None:
    """A token a module can see but no module binds is nobody's to judge."""

    bindings, visibility = build_table((owner_declaration(ProviderScope.SINGLETON),))
    visibility[AppModule][UNBOUND] = AppModule

    result = plan_scopes(
        bindings,
        visibility=visibility,
        class_dependencies={Owner: (ScopeDependency(token=UNBOUND, site=OWNER_SITE),)},
    )

    assert result.violations == ()
