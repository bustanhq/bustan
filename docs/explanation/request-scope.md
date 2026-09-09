# Request-Scoped Providers

Use request scope when a provider should exist once per incoming request and then be discarded. Typical examples are the authenticated principal, correlation ids, locale selection, request audit state, or any other data that should never leak across requests.

## Declare Request Scope

```python
from bustan import HttpRequest, Injectable


@Injectable(scope="request")
class RequestIdentity:
    def __init__(self, request: HttpRequest) -> None:
        self.request_id = request.headers.get("x-request-id", "missing")
        self.user_id = request.headers.get("x-user-id")


print(RequestIdentity.__init__.__annotations__["request"].__name__)
```

```text
HttpRequest
```

`HttpRequest` is the framework's own request type and is the one to reach for: it is the same object under every adapter, so a provider written against it is not tied to the transport the application happens to serve on. A provider may take the serving transport's own request object instead - `starlette.requests.Request` under the Starlette adapter, `AsgiHttpRequest` under the raw ASGI one - and `request.native_request` reaches that object from the neutral one. Both count as request state for the rules below. The difference is what each spelling commits you to: naming a transport's request type is a statement that this application serves on that transport, and the framework holds you to it wherever the annotation is written - on a handler parameter and on a provider constructor alike - refusing any parameter that names a request type the serving adapter does not produce. [reference/adapters.md](../reference/adapters.md#a-native-annotation-names-the-adapter-that-serves-it) explains how that is decided.

## What Request Scope Gives You

- One instance per request, shared by everything in that request that asks for it.
- Access to the request being served, through `HttpRequest` or the transport's own request object.
- Shared request-local state across route middleware, guards, pipes, interceptors, request-scoped controllers, and other request-scoped providers.

**The request scope opens before the first middleware runs and closes after the last one has returned**, rather than around the handler alone. A middleware that resolves a request-scoped provider after `call_next` therefore sees the instance the handler used, with whatever the handler wrote on it, which is what makes an audit trail or a request-local buffer flushable from a middleware at all.

Inside that window every resolution of one token answers with one instance. Two consumers resolving it at the same moment cannot end up holding different objects: the cache is written as a check and set, so an instance built second is dropped and its builder is answered with the first. Construction itself is not serialized, so a constructor with a side effect can still run twice under concurrency within one request; keep constructors free of side effects, which the scope rules already push you towards.

The window is the request's own execution context, not a span of wall clock. A task the handler awaits is inside it. A thread the handler starts itself is not: context variables do not cross a bare `threading.Thread`, so a resolution attempted from one is refused with `Request-scoped provider P requires an active request` rather than answered with another request's instance. Resolve what the thread needs before starting it, or copy the context onto it deliberately.

## When Request-Scoped Providers Are Built

Guards run first, before the controller and before any request-scoped provider either the controller or the pipeline needs. Three things follow, and applications depend on all three:

- A request-scoped provider may read what a guard wrote on `request.state`, including the authenticated principal, in its constructor.
- A request a guard rejects constructs nothing. The 403 costs the constructors nothing, so an unauthenticated caller cannot make the application do a request's worth of construction work.
- A durable provider's context key is derived after authentication too, so it may be keyed on the principal rather than only on unauthenticated client input.

The full stage order for one request is in [reference/request-pipeline.md](../reference/request-pipeline.md#execution-order).

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

Read the table in one direction only: a request-scoped provider may hold a singleton, and a singleton may not hold a request-scoped provider. `HttpRequest`, `HttpResponse`, the transport's own request and response objects, and the `REQUEST` and `RESPONSE` tokens all stand for state the server owns for one request, so they count as request-scoped state wherever they appear.

Controllers are judged by exactly these rules. A controller is cached the way a provider of the same scope is cached, and it is singleton-scoped unless its `@Controller` decorator says otherwise, so a controller that needs request-scoped providers in its constructor must be declared `scope=Scope.REQUEST`. A controller may not be durable at all: a durable instance is partitioned by a context key and a controller is not partitioned that way, so keep the per-key state in a durable provider the controller injects.

### Transients And Aliases Carry What They Reach

The rule follows the whole chain, not the first hop.

A binding that keeps no instance of its own constrains nobody by itself, so it is judged by the narrowest scope reachable *through* it. Two bindings are like this:

- a `transient` provider, which is rebuilt for every consumer, and
- a `use_existing` alias, which is a second name for a token that is already bound.

A transient that injects a request-scoped provider therefore counts as request-scoped state to whoever holds it, and a singleton that injects that transient is refused. The refusal says so in those words, as `keeps no instance of its own and reaches`, and it names the provider whose own lifetime is the reason, which is usually several hops away from the parameter the message starts with.

The one thing a transient owner may do that a cached owner may not is inject request state directly. A transient keeps nothing, so a transient provider may take `HttpRequest`, `HttpResponse`, `REQUEST` or `RESPONSE` in its constructor and be rebuilt with the current one every time. So may a request-scoped provider. A singleton or durable owner may not.

### `INQUIRER`

`INQUIRER` names the class a provider is currently being built for, so its value is different for every consumer. **It may be injected only into a transient provider.** Anything that caches an instance, whether singleton, durable, or request-scoped, would record whichever consumer resolved it first and report that same consumer to every later one, so the container refuses it.

### Factories Are Checked Too

Every token in a `use_factory` provider's `inject` list is measured against the scope the factory's result is cached under, exactly as a class constructor's parameters are. A singleton factory whose `inject` list names a request-scoped token is refused, and the error names the factory and the entry.

```python
from bustan import InjectionToken, Injectable, Module, create_app_context
from bustan.errors import ProviderResolutionError

AUDIT_SINK = InjectionToken("AUDIT_SINK")


@Injectable(scope="request")
class RequestIdentity:
    pass


def build_sink(identity: RequestIdentity) -> list[str]:
    return []


# Refused: the factory's result is cached for the process, so it would hold the first
# caller's RequestIdentity forever.
@Module(
    providers=[
        RequestIdentity,
        {"provide": AUDIT_SINK, "use_factory": build_sink, "inject": [RequestIdentity]},
    ]
)
class AppModule:
    pass


try:
    create_app_context(AppModule)
except ProviderResolutionError as error:
    print(error)
```

```text
Factory __main__.build_sink inject entry depends on request-scoped provider __main__.RequestIdentity, which can only be injected into an owner that lives no longer than it does. A singleton-scoped owner outlives it and would share one caller's instance with every later caller
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

The messages themselves are listed in [reference/errors.md](../reference/errors.md#providerresolutionerror).

## Durable Scope

A durable provider sits between a singleton and a request-scoped one: it is cached per **context key**, a value the provider derives from the request, and every request carrying the same key shares one instance. It exists for state that belongs to something longer-lived than a request but narrower than the process, such as a tenant, a customer, or a shard.

A durable class carries a `get_durable_context_key` classmethod (or staticmethod) that returns that key. It must be derivable without an instance, because the key is what selects the instance, and a durable class that declares no such hook is refused when the graph is built. The key must be hashable, and a hook returning something that is not is refused by name on the first request that asks for it, rather than by whichever cache the key reached.

```python
from bustan import HttpRequest, Injectable


@Injectable(scope="durable")
class TenantSettings:
    @classmethod
    def get_durable_context_key(cls, request: HttpRequest | None) -> str:
        if request is None:
            return "public"
        return str(getattr(request.state, "tenant", None) or "public")


print(TenantSettings.get_durable_context_key(None))
```

```text
public
```

The hook is called with the request being served, after guards have run, so it may key on anything a guard established. It is called with `None` in one place only: at startup, where the application warms the partition belonging to itself. A provider whose key can only be derived from a request has no such partition and is built as requests arrive instead. A request a guard rejects derives no key and leaves no partition behind, so an unauthenticated caller cannot populate the partition table.

Durable instances take part in every lifecycle stage, including partitions created while a request was being served. [reference/lifecycle.md](../reference/lifecycle.md#durable-providers) covers startup, teardown and ordering.

For the scope rules, `durable` is simply narrower than `singleton` and wider than `request`: a durable provider may hold singletons but not request-scoped providers, and a singleton may not hold a durable provider.

## Recommended Pattern

Keep long-lived business services singleton, keep request-local state request-scoped, and use a request-scoped controller when constructor injection needs both.

```python
from typing import Any, cast

from bustan import Controller, Get, HttpRequest, Injectable, Module, Scope, create_app
from bustan.testing import AsgiTestClient


@Injectable(scope="request")
class RequestIdentity:
    def __init__(self, request: HttpRequest) -> None:
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


app = create_app(AppModule)
with AsgiTestClient(cast(Any, app)) as client:
    print(client.get("/account/me", headers={"x-request-id": "r-1", "x-user-id": "ada"}).json())
    print(client.get("/account/me", headers={"x-request-id": "r-2", "x-user-id": "grace"}).json())
```

```text
{'request_id': 'r-1', 'user_id': 'ada', 'plan': 'pro'}
{'request_id': 'r-2', 'user_id': 'grace', 'plan': 'pro'}
```

The second caller is answered with the second caller's identity. That is the property the scope rules exist to keep, and the reason a singleton `AccountController` holding `RequestIdentity` is refused rather than served.

## Where Request Scope Fits Best

Good request-scoped responsibilities:

- authenticated principal or actor metadata
- correlation ids and audit trail data
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
- a route middleware reads it once more after `call_next`, to flush what the request recorded

That pattern is demonstrated in [../examples/request_scope_pipeline_app/README.md](../../examples/request_scope_pipeline_app/README.md).

A module registers several components under one global pipeline token either by binding a list in a single entry or by writing a separate entry for each component; both spellings run their components in the order they were declared, and mixing them under one token yields one flat list in that same order, with a list entry contributing its components in place. Every component of either spelling is resolved once per request, so any of them may be request-scoped.

## Reaching The Request Scope From Code

Constructor injection is the normal way in, and it is enough for a request-scoped controller, guard, pipe, interceptor or middleware. Where a class must look a token up rather than declare it, inject `ModuleRef` and call its `get()`: that resolves against the request in flight and hands back the same instance everything else in the request holds. `ApplicationContext.get()` does not - it resolves as though no request were being served, and refuses request scope by design. [reference/request-pipeline.md](../reference/request-pipeline.md#resolving-providers-inside-a-handler) has the details and the one thing `ModuleRef.get()` cannot do.

## Common Failure Mode

If a singleton provider or singleton controller tries to inject a request-scoped dependency, the application is refused at startup with a `ProviderResolutionError`. The fix is almost always one of these:

- move the request-local dependency into a request-scoped collaborator
- change the consumer to request scope when per-request construction is correct
- pass request-derived data as a method argument instead of constructor state

The same three fixes apply to the transitive form, where the singleton injects a transient or an alias that reaches request scope rather than injecting the request-scoped provider itself. Follow the token the message names after `reaches`: that is the provider whose lifetime the owner cannot honour.
