"""The two-request isolation matrix: every owner scope against every request-lifetime value.

The critical defect this suite exists for is a single sentence: an owner that outlives
one request must never be handed state belonging to that request, because it keeps it
and answers it to the next caller. The matrix is written out rather than argued,
because the original leaks each hid in one crossing of it.

Every crossing runs twice, with the lifespan and without it. Without is the condition
under which the leaks were reachable: nothing is constructed at startup, so the first
request builds the shared instances and the second inherits them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, cast

import pytest
from starlette.requests import Request
from starlette.responses import Response
from starlette.testclient import TestClient

from bustan import Controller, Get, Injectable, Module, Scope, create_app
from bustan.common.decorators.injectable import Inject
from bustan.core.ioc.tokens import REQUEST, RESPONSE, InjectionToken
from bustan.errors import ProviderResolutionError

if TYPE_CHECKING:
    from collections.abc import Iterator

OWNER = InjectionToken("OWNER")

# What each probed owner was handed, in the order the requests arrived. Two entries
# that are the same object are the leak this whole suite is about.
HELD: list[object] = []


@Injectable(scope=Scope.REQUEST)
class Identity:
    """A provider built for one request, from that request."""

    def __init__(self, request: Request) -> None:
        self.user = request.headers.get("x-user-id", "anonymous")


class HoldsRequestType:
    """An owner that asks for the request by its framework type."""

    def __init__(self, dependency: Request) -> None:
        self.held: object = dependency


class HoldsRequestToken:
    """An owner that asks for the request by token."""

    def __init__(self, dependency: Annotated[object, Inject(REQUEST)]) -> None:
        self.held: object = dependency


class HoldsResponseType:
    """An owner that asks for the response by its framework type."""

    def __init__(self, dependency: Response) -> None:
        self.held: object = dependency


class HoldsResponseToken:
    """An owner that asks for the response by token."""

    def __init__(self, dependency: Annotated[object, Inject(RESPONSE)]) -> None:
        self.held: object = dependency


class HoldsRequestScopedProvider:
    """An owner that asks for a provider cached for one request."""

    def __init__(self, dependency: Identity) -> None:
        self.held: object = dependency


HOLDERS: dict[str, type[object]] = {
    "starlette request": HoldsRequestType,
    "request token": HoldsRequestToken,
    "starlette response": HoldsResponseType,
    "response token": HoldsResponseToken,
    "request-scoped provider": HoldsRequestScopedProvider,
}

# An owner cached for longer than one request outlives whatever that request owned.
OUTLIVING_SCOPES = (Scope.SINGLETON, Scope.DURABLE)
PER_REQUEST_SCOPES = (Scope.REQUEST, Scope.TRANSIENT)


@Controller("/probe", scope=Scope.REQUEST)
class ProbeController:
    """Records what the owner under test was handed, once per request."""

    def __init__(self, owner: Annotated[Any, Inject(OWNER)]) -> None:
        HELD.append(owner.held)

    @Get("/")
    def read(self) -> dict[str, str]:
        return {"status": "ok"}


@pytest.fixture(autouse=True)
def _clear_held() -> Iterator[None]:
    HELD.clear()
    yield
    HELD.clear()


def durable_holder(holder: type[object]) -> type[object]:
    """Return the holder with the key hook a durable lifetime is partitioned by."""

    return type(
        f"Durable{holder.__name__}",
        (holder,),
        {"get_durable_context_key": classmethod(lambda cls, request: "one-partition")},
    )


def provider_app(holder: type[object], scope: Scope) -> Any:
    """Build an application whose OWNER provider is ``holder`` at ``scope``."""

    target = durable_holder(holder) if scope is Scope.DURABLE else holder

    @Module(
        controllers=[ProbeController],
        providers=[Identity, {"provide": OWNER, "use_class": target, "scope": scope}],
    )
    class AppModule:
        pass

    return create_app(AppModule)


def controller_app(holder: type[object], scope: Scope) -> Any:
    """Build an application whose only controller is ``holder`` at ``scope``."""

    base = durable_holder(holder) if scope is Scope.DURABLE else holder

    @Get("/")
    def read(self: Any) -> dict[str, str]:
        HELD.append(self.held)
        return {"status": "ok"}

    controller = Controller("/probe", scope=scope)(
        type("HoldingController", (base,), {"read": read})
    )

    @Module(controllers=[controller], providers=[Identity])
    class AppModule:
        pass

    return create_app(AppModule)


def probe_twice(application: Any, *, lifespan: bool) -> None:
    """Serve two requests from two different callers against one application."""

    client = TestClient(application)
    if lifespan:
        with client:
            _send_both(client)
        return
    _send_both(client)


def _send_both(client: TestClient) -> None:
    for user in ("alice", "bob"):
        assert client.get("/probe/", headers={"x-user-id": user}).status_code == 200


@pytest.mark.parametrize("dependency", list(HOLDERS), ids=list(HOLDERS))
@pytest.mark.parametrize("scope", OUTLIVING_SCOPES, ids=lambda scope: scope.value)
def test_a_provider_outliving_the_request_is_refused_request_lifetime_state(
    dependency: str, scope: Scope
) -> None:
    with pytest.raises(ProviderResolutionError):
        provider_app(HOLDERS[dependency], scope)


@pytest.mark.parametrize("dependency", list(HOLDERS), ids=list(HOLDERS))
@pytest.mark.parametrize("scope", OUTLIVING_SCOPES, ids=lambda scope: scope.value)
def test_a_controller_outliving_the_request_is_refused_request_lifetime_state(
    dependency: str, scope: Scope
) -> None:
    with pytest.raises(ProviderResolutionError):
        controller_app(HOLDERS[dependency], scope)


@pytest.mark.parametrize("lifespan", [True, False], ids=["with lifespan", "without lifespan"])
@pytest.mark.parametrize("dependency", list(HOLDERS), ids=list(HOLDERS))
@pytest.mark.parametrize("scope", PER_REQUEST_SCOPES, ids=lambda scope: scope.value)
def test_a_provider_built_per_request_sees_only_its_own_request(
    dependency: str, scope: Scope, lifespan: bool
) -> None:
    probe_twice(provider_app(HOLDERS[dependency], scope), lifespan=lifespan)

    assert len(HELD) == 2
    assert HELD[0] is not HELD[1]


@pytest.mark.parametrize("lifespan", [True, False], ids=["with lifespan", "without lifespan"])
@pytest.mark.parametrize("dependency", list(HOLDERS), ids=list(HOLDERS))
@pytest.mark.parametrize("scope", PER_REQUEST_SCOPES, ids=lambda scope: scope.value)
def test_a_controller_built_per_request_sees_only_its_own_request(
    dependency: str, scope: Scope, lifespan: bool
) -> None:
    probe_twice(controller_app(HOLDERS[dependency], scope), lifespan=lifespan)

    assert len(HELD) == 2
    assert HELD[0] is not HELD[1]


@pytest.mark.parametrize("lifespan", [True, False], ids=["with lifespan", "without lifespan"])
def test_the_second_caller_never_reads_the_first_caller_identity(lifespan: bool) -> None:
    # The critical finding, stated as the behaviour a user sees rather than as a scope
    # rule: two callers, two identities, and neither one answered to the other.
    application = provider_app(HoldsRequestScopedProvider, Scope.REQUEST)
    probe_twice(application, lifespan=lifespan)

    assert [cast(Identity, held).user for held in HELD] == ["alice", "bob"]
