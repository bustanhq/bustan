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

There is one rule, and everything below is a consequence of it.

**Every instance the container caches is cached over some context, and an owner may hold only dependencies whose state lives at least as long as the owner does.** Holding shorter-lived state keeps the first caller's data alive past that caller and serves it to the next one, which is the bug the rule exists to prevent.

The four lifetimes, and the context each one caches over:

| Scope | One instance per | May hold |
| --- | --- | --- |
| `singleton` | process | singletons |
| `durable` | context key the provider derives from the request | durables, singletons |
| `request` | request | request-scoped, durables, singletons |
| `transient` | nothing; rebuilt for every consumer | anything |

Read the table in one direction only: a request-scoped provider may hold a singleton, and a singleton may not hold a request-scoped provider. `Request`, `Response`, and the `REQUEST` and `RESPONSE` tokens stand for state the server owns for one request, so they count as request-scoped state wherever they appear.

Controllers are judged by exactly these rules. A controller is cached the way a provider of the same scope is cached, and it is singleton-scoped unless its `@Controller` decorator says otherwise, so a controller that needs request-scoped providers in its constructor must be declared `scope=Scope.REQUEST`. A controller may not be durable at all: a durable instance is partitioned by a context key and a controller is not partitioned that way, so keep the per-key state in a durable provider the controller injects.

### Transients And Aliases Carry What They Reach

The rule follows the whole chain, not the first hop.

A binding that keeps no instance of its own constrains nobody by itself, so it is judged by the narrowest scope reachable *through* it. Two bindings are like this:

- a `transient` provider, which is rebuilt for every consumer, and
- a `use_existing` alias, which is a second name for a token that is already bound.

A transient that injects a request-scoped provider therefore counts as request-scoped state to whoever holds it, and a singleton that injects that transient is refused. The refusal says so in those words, as `keeps no instance of its own and reaches`, and it names the provider whose own lifetime is the reason, which is usually several hops away from the parameter the message starts with.

The one thing a transient owner may do that a cached owner may not is inject request state directly. A transient keeps nothing, so a transient provider may take `Request`, `Response`, `REQUEST` or `RESPONSE` in its constructor and be rebuilt with the current one every time. So may a request-scoped provider. A singleton or durable owner may not.

### `INQUIRER`

`INQUIRER` names the class a provider is currently being built for, so its value is different for every consumer. **It may be injected only into a transient provider.** Anything that caches an instance, whether singleton, durable, or request-scoped, would record whichever consumer resolved it first and report that same consumer to every later one, so the container refuses it.

### Factories Are Checked Too

Every token in a `use_factory` provider's `inject` list is measured against the scope the factory's result is cached under, exactly as a class constructor's parameters are. A singleton factory whose `inject` list names a request-scoped token is refused, and the error names the factory and the entry.

```python
# Refused: the factory's result is cached for the process, so it would hold
# the first caller's RequestIdentity forever.
{"provide": AUDIT_SINK, "use_factory": build_sink, "inject": [RequestIdentity]}
```

### Binding Forms And Scope

The lifetime a binding is registered under is not always the one written beside it.

- A bare class takes the scope on its own `@Injectable()`, defaulting to `singleton`.
- `use_class` takes the target class's declared scope when it names none of its own. When it does name one, it **may narrow that scope but never widen it**: binding a request-scoped class as `transient` is allowed, binding it as `singleton` is refused. The class's declaration exists to say what its instances are safe to hold, and binding it under another token does not change that.
- `use_factory` defaults to `singleton` when it names no scope, and may not be `durable`: a durable lifetime is partitioned by a `get_durable_context_key` hook, which only a class can carry.
- `use_value` is one object that was built before the container saw it, so it is always singleton and may not name a scope.
- `use_existing` is an alias and keeps nothing of its own, so it may not name a scope either; it is judged by the token it points at.

### When The Rules Are Checked

All of this is decided once, from the declarations, before anything is built, rather than on the request that first happens to touch a bad edge. A graph that breaks the rules is refused at startup, and every broken edge is reported together under one `The application cannot be built. N problems were found:` header, so five mistakes are five messages rather than five deploys.

The messages themselves are listed in [TROUBLESHOOTING.md](TROUBLESHOOTING.md#providerresolutionerror).

## Durable Scope

A durable provider sits between a singleton and a request-scoped one: it is cached per **context key**, a value the provider derives from the request, and every request carrying the same key shares one instance. It exists for state that belongs to something longer-lived than a request but narrower than the process, such as a tenant, a customer, or a shard.

A durable class carries a `get_durable_context_key` classmethod (or staticmethod) that returns that key. It must be derivable without an instance, because the key is what selects the instance, and a durable class that declares no such hook is refused when the graph is built.

```python
from starlette.requests import Request

from bustan import Injectable


@Injectable(scope="durable")
class TenantSettings:
    @classmethod
    def get_durable_context_key(cls, request: Request | None) -> str:
        return request.headers.get("x-tenant-id", "public") if request else "public"
```

Durable instances take part in every lifecycle stage, including partitions created while a request was being served. [LIFECYCLE.md](LIFECYCLE.md#durable-providers) covers startup, teardown and ordering.

For the scope rules, `durable` is simply narrower than `singleton` and wider than `request`: a durable provider may hold singletons but not request-scoped providers, and a singleton may not hold a durable provider.

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

If a singleton provider or singleton controller tries to inject a request-scoped dependency, the application is refused at startup with a `ProviderResolutionError`. The fix is almost always one of these:

- move the request-local dependency into a request-scoped collaborator
- change the consumer to request scope when per-request construction is correct
- pass request-derived data as a method argument instead of constructor state

The same three fixes apply to the transitive form, where the singleton injects a transient or an alias that reaches request scope rather than injecting the request-scoped provider itself. Follow the token the message names after `reaches`: that is the provider whose lifetime the owner cannot honour.