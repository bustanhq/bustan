"""OL-02: APP_GUARD / APP_PIPE / APP_INTERCEPTOR / APP_FILTER providers are resolved once at
create_app time without a request, so a request-scoped global guard cannot exist, and the
one-binding-per-token rule allows at most one global guard per module.
"""

from starlette.requests import Request

from bustan import APP_GUARD, ExecutionContext, Guard, Injectable, Module, Scope, create_app
from bustan.errors import InvalidModuleError, ProviderResolutionError


@Injectable(scope=Scope.REQUEST)
class RequestGuard(Guard):
    def __init__(self, request: Request) -> None:
        self.request = request

    def can_activate(self, context: ExecutionContext) -> bool:
        return True


class AllowAll(Guard):
    def can_activate(self, context: ExecutionContext) -> bool:
        return True


class AllowAllToo(Guard):
    def can_activate(self, context: ExecutionContext) -> bool:
        return True


@Module(providers=[{"provide": APP_GUARD, "use_class": RequestGuard, "scope": "request"}])
class RequestScopedGuardModule:
    pass


def main() -> None:
    try:
        create_app(RequestScopedGuardModule)
        print("RESULT: OL-02a FIXED - request-scoped APP_GUARD accepted")
    except ProviderResolutionError as exc:
        print(f"RESULT: OL-02a REPRODUCED - request-scoped APP_GUARD rejected: {str(exc)[:70]}")

    try:
        module = Module(
            providers=[
                {"provide": APP_GUARD, "use_class": AllowAll},
                {"provide": APP_GUARD, "use_class": AllowAllToo},
            ]
        )(type("TwoGuards", (), {}))
        create_app(module)
        print("RESULT: OL-02b FIXED - two APP_GUARD bindings in one module accepted")
    except InvalidModuleError as exc:
        print(f"RESULT: OL-02b REPRODUCED - {str(exc)[:80]}")


if __name__ == "__main__":
    main()
