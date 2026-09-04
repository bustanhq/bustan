"""Integration tests for global pipeline provider tokens."""

from __future__ import annotations

from typing import Any, cast

from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import (
    APP_GUARD,
    APP_INTERCEPTOR,
    Controller,
    ExecutionContext,
    Get,
    Guard,
    Injectable,
    Interceptor,
    Module,
    Scope,
    create_app,
)
from bustan.pipeline.interceptors import CallHandler


class RejectAllGuard(Guard):
    async def can_activate(self, context: ExecutionContext) -> bool:
        return False


class AllowAllGuard(Guard):
    async def can_activate(self, context: ExecutionContext) -> bool:
        return True


@Controller("/users")
class UsersController:
    @Get("/")
    def index(self) -> dict[str, str]:
        return {"status": "ok"}


def test_app_guard_provider_applies_to_all_routes() -> None:
    @Module(
        controllers=[UsersController],
        providers=[{"provide": APP_GUARD, "use_class": RejectAllGuard}],
    )
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/users")

    assert response.status_code == 403


def test_overriding_a_global_guard_before_startup_disables_it() -> None:
    @Module(
        controllers=[UsersController],
        providers=[{"provide": APP_GUARD, "use_class": RejectAllGuard}],
    )
    class AppModule:
        pass

    application = create_app(AppModule)
    application.container.override(APP_GUARD, AllowAllGuard())

    assert application.container.has_override(APP_GUARD)
    with TestClient(cast(Any, application)) as client:
        response = client.get("/users")

    assert response.status_code == 200


def test_a_module_may_declare_several_global_guards_and_all_of_them_run() -> None:
    calls: list[str] = []

    class FirstGuard(Guard):
        def can_activate(self, context: ExecutionContext) -> bool:
            calls.append("first")
            return True

    class SecondGuard(Guard):
        def can_activate(self, context: ExecutionContext) -> bool:
            calls.append("second")
            return True

    @Module(
        controllers=[UsersController],
        providers=[{"provide": APP_GUARD, "use_value": [FirstGuard(), SecondGuard()]}],
    )
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        assert client.get("/users").status_code == 200

    assert calls == ["first", "second"]


def test_a_request_scoped_global_guard_is_built_once_for_each_request() -> None:
    identities: list[int] = []

    @Injectable(scope=Scope.REQUEST)
    class RequestScopedGuard(Guard):
        def __init__(self, request: Request) -> None:
            self.path = request.url.path

        def can_activate(self, context: ExecutionContext) -> bool:
            identities.append(id(self))
            return True

    @Module(
        controllers=[UsersController],
        providers=[
            {"provide": APP_GUARD, "use_class": RequestScopedGuard, "scope": "request"},
        ],
    )
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        assert client.get("/users").status_code == 200
        assert client.get("/users").status_code == 200

    assert len(identities) == 2
    assert len(set(identities)) == 2


def test_a_global_guard_built_by_an_async_callable_object_is_awaited() -> None:
    class AsyncGuardFactory:
        """A factory whose asynchrony is carried by ``__call__`` rather than the name."""

        async def __call__(self) -> Guard:
            return AllowAllGuard()

    @Module(
        controllers=[UsersController],
        providers=[
            {
                "provide": APP_GUARD,
                "use_factory": AsyncGuardFactory(),
                "scope": "request",
            }
        ],
    )
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        assert client.get("/users").status_code == 200


def test_global_providers_declared_by_several_modules_run_in_registration_order() -> None:
    calls: list[str] = []

    class FeatureGuard(Guard):
        def can_activate(self, context: ExecutionContext) -> bool:
            calls.append("feature")
            return True

    class RootGuard(Guard):
        def can_activate(self, context: ExecutionContext) -> bool:
            calls.append("root")
            return True

    @Module(providers=[{"provide": APP_GUARD, "use_class": FeatureGuard}])
    class FeatureModule:
        pass

    @Module(
        imports=[FeatureModule],
        controllers=[UsersController],
        providers=[{"provide": APP_GUARD, "use_class": RootGuard}],
    )
    class AppModule:
        pass

    application = create_app(AppModule)
    with TestClient(cast(Any, application)) as client:
        assert client.get("/users").status_code == 200

    declaring_modules = [
        node.key
        for node in application.module_graph.nodes
        if (node.key, APP_GUARD) in application.container.registry.bindings
    ]
    assert declaring_modules == [AppModule, FeatureModule]
    assert calls == ["root", "feature"]


def test_a_global_interceptor_sees_the_request_it_was_built_for() -> None:
    observed: list[str] = []

    @Injectable(scope=Scope.REQUEST)
    class RecordingInterceptor(Interceptor):
        def __init__(self, request: Request) -> None:
            self.path = request.url.path

        async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
            observed.append(self.path)
            return await next.handle()

    @Module(
        controllers=[UsersController],
        providers=[
            {
                "provide": APP_INTERCEPTOR,
                "use_class": RecordingInterceptor,
                "scope": "request",
            }
        ],
    )
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        assert client.get("/users").status_code == 200

    assert observed == ["/users"]
