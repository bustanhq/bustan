# Request-Scoped Providers

Use request scope when a provider should exist once per incoming request and then be discarded.

## Declare Request Scope

```python
from star import injectable
from starlette.requests import Request


@injectable(scope="request")
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

- Request-scoped providers may depend on `Request`.
- Request-scoped providers may depend on other request-scoped providers.
- Singleton and transient providers must not depend on request-scoped providers, because request-local state cannot be promoted into a longer-lived object.

## Example Pattern

Keep long-lived business services singleton, and inject the request-local provider into the controller or other request-scoped collaborators:

```python
@injectable
class BillingService:
    def read_plan(self, user_id: str) -> dict[str, str]:
        return {"user_id": user_id, "plan": "pro"}


@controller("/account")
class AccountController:
    def __init__(self, billing_service: BillingService, request_identity: RequestIdentity) -> None:
        self.billing_service = billing_service
        self.request_identity = request_identity

    @get("/me")
    def read_account(self) -> dict[str, str]:
        return self.billing_service.read_plan(self.request_identity.user_id or "anonymous")
```