# Request-Scoped Providers

Use request scope when a provider should exist once per incoming request and then be discarded.

## Declare Request Scope

```python
from bustan import Injectable
from starlette.requests import Request


@Injectable(scope="request")
class RequestIdentity:
    def __init__(self, request: Request) -> None:
        self.request_id = request.headers.get("x-request-id", "missing")
        self.user_id = request.headers.get("x-user-id")
```

## What Request Scope Gives You

- One cached instance per request.
- Safe access to Starlette's `Request` object.
- Shared request-local state across controllers, guards, pipes, and interceptors.

## Scope Rules

Every instance is cached over some context: a singleton over the whole process, a durable
provider over its partition, a request-scoped provider over one request, a transient over
nothing at all. An instance may only hold dependencies cached over a context at least as wide
as its own. Holding a narrower one keeps the first caller's state alive past that caller and
serves it to the next.

- Request-scoped providers may depend on `Request`, on other request-scoped providers, and on
  durable and singleton providers.
- Durable providers may depend on durable and singleton providers. They may **not** depend on
  `Request` or on request-scoped providers: a durable instance is retained for the life of its
  partition, so it would hand the first caller's headers to every later caller routed there.
- Singleton providers may depend only on other singletons. They may **not** depend on `Request`,
  on request-scoped providers, or on durable providers.
- Transient providers are constructed fresh for whoever asks and may depend on anything.

A graph that breaks these rules raises `ProviderResolutionError` while the application is being
assembled, before it can accept traffic.

## Controllers Have Scopes Too

A controller is subject to the same rules, and **a controller with no `scope=` is a singleton**.
It is built once and reused for every request, so it cannot hold request-scoped state:

```python
@Controller("/account")  # singleton: rejected at start-up
class AccountController:
    def __init__(self, request_identity: RequestIdentity) -> None: ...
```

Declare the controller request-scoped whenever it injects a request-scoped provider. Long-lived
business services stay singleton and are injected alongside; a request-scoped controller may
hold both.

Durable scope is not available to controllers. A controller has no partition key of its own, so
a durable controller would be built once and shared by every partition it was declared to keep
apart. `@Controller(scope=Scope.DURABLE)` raises `InvalidControllerError` at start-up. Declare
the controller request-scoped or transient and inject a durable-scoped provider instead.

## Example Pattern

```python
from bustan import Controller, Get, Scope


@Injectable
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
        return self.billing_service.read_plan(self.request_identity.user_id or "anonymous")
```

## Binding A Provider Under Another Token

A class carries the scope its author declared on it, and binding it under an interface token
keeps that scope:

```python
# RequestAudit is @Injectable(scope="request"), so this binding is request-scoped too.
@Module(providers=[{"provide": AuditPort, "use_class": RequestAudit}])
class AuditModule:
    pass
```

An explicit `scope` in the dict may narrow the declared scope but never widen it. Widening
raises `InvalidProviderError`, because a wider scope shares one caller's state with every later
caller.
