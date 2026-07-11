# Request-Scoped Providers

Use request scope when a provider should exist once per incoming request and then be discarded. Typical examples are authentication context, correlation IDs, locale selection, request audit state, or other data that should never leak across requests.

## Declare Request Scope

```python
from starlette.requests import Request

from bustan import Injectable


@Injectable(scope="request")
class RequestIdentity:
    def __init__(self, request: Request) -> None:
        self.request_id = request.headers.get("x-request-id", "missing")
        self.user_id = request.headers.get("x-user-id")
```

## What Request Scope Gives You

- One cached instance per request.
- Safe access to the native Starlette `Request` object.
- Shared request-local state across request-scoped controllers, guards, pipes, interceptors, and other request-scoped providers.

If two request-scoped components depend on the same request-scoped provider during one request, they receive the same cached instance for that request.

## Scope Rules

- Request-scoped providers may depend on `Request`.
- Request-scoped providers may depend on other request-scoped providers.
- Singleton or transient providers must not depend on request-scoped providers.
- Singleton controllers must not depend on request-scoped providers either.
- When a controller needs request-scoped providers in its constructor, mark the controller itself as request-scoped.

That last rule matters because controllers are singleton-scoped by default.

## Recommended Pattern

Keep long-lived business services singleton, keep request-local state request-scoped, and use a request-scoped controller when constructor injection needs both.

```python
from starlette.requests import Request

from bustan import Controller, Get, Injectable, Module, Scope


@Injectable(scope="request")
class RequestIdentity:
    def __init__(self, request: Request) -> None:
        self.request_id = request.headers.get("x-request-id", "missing")
        self.user_id = request.headers.get("x-user-id", "anonymous")


@Injectable()
class BillingService:
    def read_plan(self, user_id: str) -> dict[str, str]:
        return {"user_id": user_id, "plan": "pro"}


@Controller("/account", scope=Scope.REQUEST)
class AccountController:
    def __init__(self, billing_service: BillingService, request_identity: RequestIdentity) -> None:
        self.billing_service = billing_service
        self.request_identity = request_identity

    @Get("/me")
    def read_account(self) -> dict[str, str]:
        return {
            "request_id": self.request_identity.request_id,
            **self.billing_service.read_plan(self.request_identity.user_id),
        }


@Module(
    controllers=[AccountController],
    providers=[BillingService, RequestIdentity],
)
class AppModule:
    pass
```

## Where Request Scope Fits Best

Good request-scoped responsibilities:

- authenticated principal or actor metadata
- correlation IDs and audit trail data
- parsed request policy context
- per-request caches that should be reused during one request only

Poor request-scoped responsibilities:

- database pools
- configuration services
- long-lived repositories or SDK clients
- anything that should be shared across requests

## Pipeline Components

Request scope is especially useful when the same request-local state must be shared across multiple pipeline stages.

For example:

- a guard checks that `RequestIdentity.user_id` exists
- an interceptor adds `RequestIdentity.request_id` to the response envelope
- a request-scoped controller reads the same provider again in the handler

That pattern is demonstrated in [../examples/request_scope_pipeline_app/README.md](../examples/request_scope_pipeline_app/README.md).

## Common Failure Mode

If a singleton provider or singleton controller tries to inject a request-scoped dependency, you should expect a `ProviderResolutionError`. The fix is almost always one of these:

- move the request-local dependency into a request-scoped collaborator
- change the consumer to request scope when per-request construction is correct
- pass request-derived data as a method argument instead of constructor state