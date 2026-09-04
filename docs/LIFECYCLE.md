# Lifecycle Hooks

Modules and providers can participate in application startup and shutdown. Bustan wires those lifecycle stages into the Starlette lifespan handler for HTTP applications, and `ApplicationContext` exposes the same semantics for non-HTTP bootstrapping.

## Supported Hook Names

- `on_module_init(self)`
- `on_application_bootstrap(self)`
- `before_application_shutdown(self, signal: str | None)`
- `on_application_shutdown(self, signal: str | None)`
- `on_module_destroy(self)`

Each hook may be synchronous or asynchronous.

`signal` names the signal that asked the process to stop. No adapter supplies one yet, so it is always `None`; the parameter is part of the hook signature so that applications written against it keep working when an adapter starts passing a real signal name.

## Who Receives Provider Hooks

A provider hook runs on the instances Bustan itself built: those declared as a class, through `use_class`, or through `use_factory`.

- An object registered with `use_value` was built by the application before it was handed over, so Bustan neither initializes nor destroys it. Whatever created it owns its lifetime.
- `use_existing` is a second name for a token that is already bound, so it adds no participant; the aliased provider receives its hooks once, under its own token.
- One object registered under two tokens receives each hook exactly once. Participants are identified by object identity, not by token.
- Controllers do not take part. A controller method without an HTTP route decorator is refused while the application is built, so a controller cannot declare a hook at all; put the work in a provider the controller injects.

An error raised by a provider hook names the token the instance was built for, so a failing hook can be traced back to the declaration that registered it.

## Ordering

For module classes, Bustan walks the discovered module graph in root-first order during startup and reverse order during shutdown.

Startup stages:

1. `on_module_init`
2. `on_application_bootstrap`

Shutdown stages:

1. `before_application_shutdown`
2. `on_application_shutdown`
3. `on_module_destroy`

Within each stage the module hooks run first and the provider hooks run after the module stage completes.

Provider hooks run in construction order. Startup builds every provider that exists before the first request in one pass, awaiting each one, and a provider's dependencies are built before the provider itself, so construction order is dependency-first. Every teardown stage reverses that order, so a dependent is always torn down before what it depends on.

## Durable Providers

A durable provider partitions its instances by a key it derives from the request. Startup warms the partition belonging to the application itself, by asking the provider for its context key with no request in flight; a provider whose key can only be derived from a request has no such partition and is built as requests arrive instead.

Every durable instance takes part in every teardown stage, including a partition created while a request was being served. Durable instances are torn down before singletons, because they are the younger of the two.

## Example

```python
from bustan import Injectable, Module


@Injectable()
class DatabasePool:
    async def on_application_bootstrap(self) -> None:
        print("database connected")

    async def before_application_shutdown(self, signal: str | None) -> None:
        print(f"draining connections before shutdown ({signal})")

    async def on_module_destroy(self) -> None:
        print("database disposed")


@Module(providers=[DatabasePool], exports=[DatabasePool])
class DatabaseModule:
    def on_module_init(self) -> None:
        print("database module discovered")


@Module(imports=[DatabaseModule])
class AppModule:
    def on_application_bootstrap(self) -> None:
        print("application ready")

    def on_application_shutdown(self, signal: str | None) -> None:
        print(f"application shutting down ({signal})")
```

## `create_app()` Versus `create_app_context()`

- `create_app(AppModule)` compiles routes, constructs the HTTP adapter, and runs lifecycle stages through the platform lifespan.
- `create_app_context(AppModule)` builds only the DI application context. Call `await context.init()` to run startup hooks and `await context.close()` to run shutdown hooks.

That makes `ApplicationContext` useful for non-HTTP jobs, focused bootstrap tests, and integration helpers that need DI plus lifecycle but no server.

Example:

```python
from bustan import create_app_context


context = create_app_context(AppModule)
await context.init()
service = context.get(DatabasePool)
await context.close()
```

## After Shutdown

Shutdown destroys the instances the application built, so it also drops them: the singleton, durable and controller caches are emptied once the last teardown stage has run.

Startup may then run again. A second `await context.init()`, or a second `with TestClient(app)` block over the same application, builds a fresh set of instances from the same module graph and runs every startup hook over them again. Resolving a provider between a shutdown and the next startup builds a new instance rather than handing back a destroyed one.

The graph, the container and the compiled routes are built once and are not rebuilt by a second startup; only the instances are.

## Failure Behavior

- Hook failures are wrapped in `LifecycleError`.
- A failing startup hook stops application bootstrap before the app starts serving traffic.
- A startup that fails part-way tears down whatever it had already built, in reverse construction order, before the failure propagates. The failure that reaches the caller is the one that stopped startup; a hook that also failed while undoing it is recorded as a note on that exception. The application is left closed, so a later `close()` does not run teardown a second time.
- Every teardown stage runs to completion even when a hook fails, so one failing component cannot leak another component's resources.
- One failed teardown hook is raised on its own. More than one is raised together as an `ExceptionGroup`, which is also a `LifecycleError`; each member names the hook that failed and keeps the original exception as its `__cause__`.

If you need request-time cleanup or response shaping instead of process lifecycle behavior, use the request pipeline hooks described in [REQUEST_PIPELINE.md](REQUEST_PIPELINE.md) instead.
