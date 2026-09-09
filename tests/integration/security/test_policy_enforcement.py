"""Integration tests for the policy decorators that carry a behaviour of their own.

Every test here drives a served request through a built application, because what these
three decorators are for is what happens to a request. A route's compiled plan carrying
the policy proves only that the declaration arrived somewhere, which is what these
decorators did before they did anything.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import pytest

from bustan import Controller, Delete, Get, Module, Post, ValueProvider, create_app
from bustan.contracts import HttpRequest, HttpResponse
from bustan.kernel.errors import InvalidPipelineError, RouteDefinitionError
from bustan.observability.logger import FRAMEWORK_LOGGER_NAME, Logger
from bustan.security import AUTHENTICATOR_REGISTRY, Audit, Auth, Cache, Idempotent
from bustan.security import policy as policy_module
from bustan.testing import AsgiTestClient

if TYPE_CHECKING:
    from bustan.pipeline.context import ExecutionContext


@dataclass(frozen=True, slots=True)
class PrincipalStub:
    """A caller with the three fields the framework reads off a principal."""

    id: str
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()


class HeaderAuthenticator:
    """Identifies each request as whoever its ``x-caller`` header names."""

    async def authenticate(self, context: ExecutionContext) -> PrincipalStub | None:
        request = context.request
        if request is None:
            return None
        caller = request.headers.get("x-caller")
        return None if caller is None else PrincipalStub(id=caller)


def _client(module: type[object]) -> AsgiTestClient:
    """Serve *module* through the framework's own transport-neutral test client."""

    return AsgiTestClient(cast(Any, create_app(module)))


def _audit_records(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    """Return every audit record the framework logger wrote, decoded."""

    return [
        decoded
        for decoded in (
            json.loads(record.getMessage())
            for record in caplog.records
            if record.name == FRAMEWORK_LOGGER_NAME
        )
        if decoded.get("context") == policy_module.AUDIT_LOG_CONTEXT
    ]


def test_cache_answers_a_repeated_read_without_running_the_handler_again() -> None:
    runs: list[int] = []

    @Controller("/reports")
    class ReportsController:
        @Cache(ttl=60)
        @Get("/")
        def read_reports(self) -> dict[str, int]:
            runs.append(1)
            return {"runs": len(runs)}

    @Module(controllers=[ReportsController])
    class AppModule:
        pass

    with _client(AppModule) as client:
        first = client.get("/reports")
        second = client.get("/reports")

    assert len(runs) == 1
    assert first.json() == {"runs": 1}
    assert second.json() == {"runs": 1}


def test_cache_keeps_two_query_strings_apart() -> None:
    runs: list[str] = []

    @Controller("/reports")
    class ReportsController:
        @Cache(ttl=60)
        @Get("/")
        def read_reports(self) -> dict[str, int]:
            runs.append("run")
            return {"runs": len(runs)}

    @Module(controllers=[ReportsController])
    class AppModule:
        pass

    with _client(AppModule) as client:
        first = client.get("/reports", params={"region": "eu"})
        second = client.get("/reports", params={"region": "us"})
        repeated = client.get("/reports", params={"region": "eu"})

    assert len(runs) == 2
    assert first.json() == {"runs": 1}
    assert second.json() == {"runs": 2}
    assert repeated.json() == {"runs": 1}


def test_cache_stops_answering_once_the_ttl_has_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    runs: list[int] = []
    now = [1_000.0]

    monkeypatch.setattr(policy_module, "monotonic", lambda: now[0])

    @Controller("/reports")
    class ReportsController:
        @Cache(ttl=60)
        @Get("/")
        def read_reports(self) -> dict[str, int]:
            runs.append(1)
            return {"runs": len(runs)}

    @Module(controllers=[ReportsController])
    class AppModule:
        pass

    with _client(AppModule) as client:
        client.get("/reports")
        now[0] += 59
        inside_ttl = client.get("/reports")
        now[0] += 2
        past_ttl = client.get("/reports")

    assert len(runs) == 2
    assert inside_ttl.json() == {"runs": 1}
    assert past_ttl.json() == {"runs": 2}


def test_cache_does_not_answer_one_caller_with_another_callers_response() -> None:
    @Auth("header")
    @Controller("/profile")
    class ProfileController:
        @Cache(ttl=60)
        @Get("/")
        def read_profile(self, request: HttpRequest) -> dict[str, str]:
            principal = cast(PrincipalStub, request.state.principal)
            return {"caller": principal.id}

    @Module(
        controllers=[ProfileController],
        providers=[
            ValueProvider(
                provide=AUTHENTICATOR_REGISTRY, use_value={"header": HeaderAuthenticator()}
            )
        ],
    )
    class AppModule:
        pass

    with _client(AppModule) as client:
        first = client.get("/profile", headers={"x-caller": "ada"})
        second = client.get("/profile", headers={"x-caller": "grace"})
        repeated = client.get("/profile", headers={"x-caller": "ada"})

    assert first.json() == {"caller": "ada"}
    assert second.json() == {"caller": "grace"}
    assert repeated.json() == {"caller": "ada"}


def test_cache_drops_its_oldest_answer_once_it_is_full() -> None:
    runs: list[str] = []

    @Controller("/reports")
    class ReportsController:
        @Cache(ttl=600)
        @Get("/")
        def read_reports(self) -> dict[str, int]:
            runs.append("run")
            return {"runs": len(runs)}

    @Module(controllers=[ReportsController])
    class AppModule:
        pass

    limit = policy_module.CACHE_ENTRY_LIMIT
    with _client(AppModule) as client:
        for index in range(limit):
            client.get("/reports", params={"page": str(index)})
        held = len(runs)
        # One more distinct query than the store may hold, so the first page's answer is
        # the one dropped and asking for it again has to recompute it.
        client.get("/reports", params={"page": str(limit)})
        client.get("/reports", params={"page": "0"})
        recent = client.get("/reports", params={"page": str(limit - 1)})

    assert held == limit
    assert len(runs) == limit + 2
    assert recent.json() == {"runs": limit}


def test_a_controller_wide_cache_does_not_answer_one_route_with_another_route() -> None:
    """One interceptor covers every route under the controller, keyed by the handler."""

    @Cache(ttl=60)
    @Controller("/reports")
    class ReportsController:
        @Get("/daily")
        def read_daily(self) -> dict[str, str]:
            return {"report": "daily"}

        @Get("/weekly")
        def read_weekly(self) -> dict[str, str]:
            return {"report": "weekly"}

    @Module(controllers=[ReportsController])
    class AppModule:
        pass

    with _client(AppModule) as client:
        daily = client.get("/reports/daily")
        weekly = client.get("/reports/weekly")
        repeated = client.get("/reports/daily")

    assert daily.json() == {"report": "daily"}
    assert weekly.json() == {"report": "weekly"}
    assert repeated.json() == {"report": "daily"}


def test_cache_does_not_replay_a_method_that_may_change_something() -> None:
    runs: list[int] = []

    @Controller("/reports")
    class ReportsController:
        @Cache(ttl=60)
        @Post("/")
        def create_report(self) -> dict[str, int]:
            runs.append(1)
            return {"runs": len(runs)}

    @Module(controllers=[ReportsController])
    class AppModule:
        pass

    with _client(AppModule) as client:
        client.post("/reports")
        second = client.post("/reports")

    assert len(runs) == 2
    assert second.json() == {"runs": 2}


def test_cache_refuses_a_ttl_that_would_expire_before_it_answered() -> None:
    with pytest.raises(InvalidPipelineError, match="at least one second"):
        Cache(ttl=0)


def test_cache_is_refused_on_a_route_whose_body_can_only_be_read_once() -> None:
    @Controller("/downloads")
    class DownloadsController:
        @Cache(ttl=60)
        @Get("/")
        def read_download(self) -> HttpResponse:
            return HttpResponse.json({"status": "ok"})

    @Module(controllers=[DownloadsController])
    class AppModule:
        pass

    with pytest.raises(RouteDefinitionError, match="mutates the response body"):
        create_app(AppModule)


def test_idempotent_answers_a_retry_from_what_the_first_attempt_returned() -> None:
    runs: list[int] = []

    @Controller("/orders")
    class OrdersController:
        @Idempotent()
        @Post("/")
        def place_order(self) -> dict[str, int]:
            runs.append(1)
            return {"orders": len(runs)}

    @Module(controllers=[OrdersController])
    class AppModule:
        pass

    with _client(AppModule) as client:
        first = client.post("/orders", headers={"Idempotency-Key": "attempt-1"})
        retry = client.post("/orders", headers={"Idempotency-Key": "attempt-1"})

    assert len(runs) == 1
    assert first.json() == {"orders": 1}
    assert retry.json() == {"orders": 1}


def test_idempotent_reads_the_header_the_route_named() -> None:
    runs: list[int] = []

    @Controller("/orders")
    class OrdersController:
        @Idempotent(key_header="X-Request-Id")
        @Post("/")
        def place_order(self) -> dict[str, int]:
            runs.append(1)
            return {"orders": len(runs)}

    @Module(controllers=[OrdersController])
    class AppModule:
        pass

    with _client(AppModule) as client:
        client.post("/orders", headers={"X-Request-Id": "attempt-1"})
        retry = client.post("/orders", headers={"X-Request-Id": "attempt-1"})
        other_key = client.post("/orders", headers={"X-Request-Id": "attempt-2"})
        unkeyed = client.post("/orders")

    assert len(runs) == 3
    assert retry.json() == {"orders": 1}
    assert other_key.json() == {"orders": 2}
    assert unkeyed.json() == {"orders": 3}


def test_idempotent_keeps_one_key_apart_from_another_resource() -> None:
    deleted: list[str] = []

    @Controller("/orders")
    class OrdersController:
        @Idempotent()
        @Delete("/{order_id}")
        def cancel_order(self, order_id: str) -> dict[str, int]:
            deleted.append(order_id)
            return {"cancelled": len(deleted)}

    @Module(controllers=[OrdersController])
    class AppModule:
        pass

    with _client(AppModule) as client:
        client.delete("/orders/1", headers={"Idempotency-Key": "attempt-1"})
        other_resource = client.delete("/orders/2", headers={"Idempotency-Key": "attempt-1"})
        retry = client.delete("/orders/1", headers={"Idempotency-Key": "attempt-1"})

    assert deleted == ["1", "2"]
    assert other_resource.json() == {"cancelled": 2}
    assert retry.json() == {"cancelled": 1}


def test_idempotent_forgets_a_key_once_its_retention_window_has_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs: list[int] = []
    now = [1_000.0]

    monkeypatch.setattr(policy_module, "monotonic", lambda: now[0])

    @Controller("/orders")
    class OrdersController:
        @Idempotent()
        @Post("/")
        def place_order(self) -> dict[str, int]:
            runs.append(1)
            return {"orders": len(runs)}

    @Module(controllers=[OrdersController])
    class AppModule:
        pass

    with _client(AppModule) as client:
        client.post("/orders", headers={"Idempotency-Key": "attempt-1"})
        now[0] += policy_module.IDEMPOTENCY_RETENTION_SECONDS + 1
        after_retention = client.post("/orders", headers={"Idempotency-Key": "attempt-1"})

    assert len(runs) == 2
    assert after_retention.json() == {"orders": 2}


def test_audit_writes_a_record_naming_the_event_after_the_handler_runs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=FRAMEWORK_LOGGER_NAME)
    Logger.reset_logger()

    @Auth("header")
    @Controller("/users")
    class UsersController:
        @Audit(event="user.delete")
        @Delete("/{user_id}")
        def remove_user(self, user_id: str) -> dict[str, str]:
            return {"removed": user_id}

    @Module(
        controllers=[UsersController],
        providers=[
            ValueProvider(
                provide=AUTHENTICATOR_REGISTRY, use_value={"header": HeaderAuthenticator()}
            )
        ],
    )
    class AppModule:
        pass

    with _client(AppModule) as client:
        response = client.delete("/users/7", headers={"x-caller": "ada"})

    assert response.status_code == 200
    [record] = _audit_records(caplog)
    assert record["event"] == "user.delete"
    assert record["message"] == "user.delete"
    assert record["succeeded"] is True
    assert record["principal"] == "ada"
    assert record["operation"] == "UsersController.remove_user"
    assert record["route"] == "DELETE /users/{user_id}"
    assert "failure" not in record


def test_audit_writes_a_record_when_the_handler_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=FRAMEWORK_LOGGER_NAME)
    Logger.reset_logger()

    @Controller("/users")
    class UsersController:
        @Audit(event="user.delete")
        @Delete("/{user_id}")
        def remove_user(self, user_id: str) -> dict[str, str]:
            raise ValueError("nothing to remove")

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    with _client(AppModule) as client:
        response = client.delete("/users/7")

    assert response.status_code == 500
    [record] = _audit_records(caplog)
    assert record["event"] == "user.delete"
    assert record["succeeded"] is False
    assert record["failure"] == "ValueError"
    assert "principal" not in record


def test_audit_carries_nothing_the_caller_sent(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger=FRAMEWORK_LOGGER_NAME)
    Logger.reset_logger()

    @Controller("/users")
    class UsersController:
        @Audit(event="user.search")
        @Get("/")
        def search_users(self) -> dict[str, str]:
            return {"status": "ok"}

    @Module(controllers=[UsersController])
    class AppModule:
        pass

    with _client(AppModule) as client:
        client.get(
            "/users",
            params={"q": "secret-term"},
            headers={"authorization": "Bearer secret-token"},
        )

    [record] = _audit_records(caplog)
    assert "secret-term" not in json.dumps(record)
    assert "secret-token" not in json.dumps(record)
