"""Integration tests for global pipeline provider tokens."""

from __future__ import annotations

from typing import Any, cast

import pytest
from starlette.requests import Request
from starlette.testclient import TestClient

from bustan import (
    APP_FILTER,
    APP_GUARD,
    APP_INTERCEPTOR,
    APP_PIPE,
    Controller,
    ExceptionFilter,
    ExecutionContext,
    Get,
    Guard,
    Injectable,
    Interceptor,
    Module,
    Pipe,
    Scope,
    create_app,
)
from bustan.errors import InvalidModuleError
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


def test_two_global_guard_entries_in_one_module_both_run_in_declaration_order() -> None:
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
        providers=[
            {"provide": APP_GUARD, "use_class": FirstGuard},
            {"provide": APP_GUARD, "use_class": SecondGuard},
        ],
    )
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        assert client.get("/users").status_code == 200

    assert calls == ["first", "second"]


def test_two_global_pipe_entries_in_one_module_both_transform_in_declaration_order() -> None:
    class Exclaim(Pipe):
        def transform(self, value: object, context: ExecutionContext) -> object:
            return f"{value}!"

    class Wrap(Pipe):
        def transform(self, value: object, context: ExecutionContext) -> object:
            return f"[{value}]"

    @Controller("/greetings")
    class GreetingsController:
        @Get("/{name}")
        def greet(self, name: str) -> dict[str, str]:
            return {"name": name}

    @Module(
        controllers=[GreetingsController],
        providers=[
            {"provide": APP_PIPE, "use_class": Exclaim},
            {"provide": APP_PIPE, "use_class": Wrap},
        ],
    )
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/greetings/ada")

    # Written the other way round the answer would be "[ada]!", so the order the module
    # declares its pipes in is the order they transform in.
    assert response.json() == {"name": "[ada!]"}


def test_two_global_interceptor_entries_in_one_module_both_wrap_in_declaration_order() -> None:
    calls: list[str] = []

    class FirstInterceptor(Interceptor):
        async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
            calls.append("first-in")
            result = await next.handle()
            calls.append("first-out")
            return result

    class SecondInterceptor(Interceptor):
        async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
            calls.append("second-in")
            result = await next.handle()
            calls.append("second-out")
            return result

    @Module(
        controllers=[UsersController],
        providers=[
            {"provide": APP_INTERCEPTOR, "use_class": FirstInterceptor},
            {"provide": APP_INTERCEPTOR, "use_class": SecondInterceptor},
        ],
    )
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        assert client.get("/users").status_code == 200

    assert calls == ["first-in", "second-in", "second-out", "first-out"]


def test_two_global_filter_entries_in_one_module_are_both_offered_the_error() -> None:
    calls: list[str] = []

    class Failing(Exception):
        pass

    class EarlierFilter(ExceptionFilter):
        exception_types = (Failing,)

        def catch(self, exc: Exception, context: ExecutionContext) -> object:
            calls.append("earlier")
            return {"handled": "earlier"}

    class LaterFilter(ExceptionFilter):
        exception_types = (Failing,)

        def catch(self, exc: Exception, context: ExecutionContext) -> object:
            calls.append("later")
            return None

    @Controller("/broken")
    class BrokenController:
        @Get("/")
        def fail(self) -> dict[str, str]:
            raise Failing

    @Module(
        controllers=[BrokenController],
        providers=[
            {"provide": APP_FILTER, "use_class": EarlierFilter},
            {"provide": APP_FILTER, "use_class": LaterFilter},
        ],
    )
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        response = client.get("/broken")

    # Both entries are registered, and the existing precedence among equally specific
    # filters decides which is asked first: the one declared nearest the error, which is
    # the last of the two. It declined, so the earlier one was asked and answered.
    assert calls == ["later", "earlier"]
    assert response.json() == {"handled": "earlier"}


def test_separate_entries_and_a_list_entry_mix_into_one_declaration_order() -> None:
    calls: list[str] = []

    def recording_guard(name: str) -> type[Guard]:
        class Recording(Guard):
            def can_activate(self, context: ExecutionContext) -> bool:
                calls.append(name)
                return True

        return Recording

    @Injectable(scope=Scope.REQUEST)
    class RequestScopedGuard(Guard):
        def __init__(self, request: Request) -> None:
            self.path = request.url.path

        def can_activate(self, context: ExecutionContext) -> bool:
            calls.append(f"request:{self.path}")
            return True

    Second = recording_guard("second")
    Third = recording_guard("third")

    @Module(
        controllers=[UsersController],
        providers=[
            {"provide": APP_GUARD, "use_class": recording_guard("first")},
            {"provide": APP_GUARD, "use_value": [Second(), Third()]},
            {"provide": APP_GUARD, "use_class": RequestScopedGuard, "scope": "request"},
        ],
    )
    class AppModule:
        pass

    with TestClient(cast(Any, create_app(AppModule))) as client:
        assert client.get("/users").status_code == 200

    assert calls == ["first", "second", "third", "request:/users"]


def test_a_second_entry_for_an_ordinary_token_is_still_refused() -> None:
    class Service:
        pass

    @Module(controllers=[UsersController], providers=[Service, Service])
    class AppModule:
        pass

    with pytest.raises(InvalidModuleError, match="duplicate entries in providers"):
        create_app(AppModule)
