# Lifecycle Hooks

Modules and providers can participate in application startup and shutdown. An HTTP application runs those stages through the serving adapter's lifespan, whichever adapter that is, and `ApplicationContext` exposes the same semantics for a process that serves no HTTP at all.

## Supported Hook Names

- `on_module_init(self)`
- `on_application_bootstrap(self)`
- `before_application_shutdown(self, signal: str | None)`
- `on_application_shutdown(self, signal: str | None)`
- `on_module_destroy(self)`

Each hook may be synchronous or asynchronous.

`signal` names the signal that asked the process to stop, as the platform names it: `"SIGTERM"` or `"SIGINT"`. It is `None` when nothing signalled the process and a caller asked for the shutdown instead, which is what `await context.close()` and `await app.close()` do, and `None` again when the application was started and stopped through a test client rather than by serving a port. The name comes from the adapter, which is the only layer that sees the signal: the shipped Starlette adapter records it in `app.listen()` and passes it on, and an adapter whose transport does not report one passes `None` always.

## Who Receives Provider Hooks

A provider hook runs on the instances Bustan itself built: those declared as a class, through `use_class`, or through `use_factory`.

- An object registered with `use_value` was built by the application before it was handed over, so Bustan neither initializes nor destroys it. Whatever created it owns its lifetime.
- `use_existing` is a second name for a token that is already bound, so it adds no participant; the aliased provider receives its hooks once, under its own token.
- One object registered under two tokens receives each hook exactly once. Participants are identified by object identity, not by token.
- Controllers do not take part. A controller method without an HTTP route decorator is refused while the application is built, so a controller cannot declare a hook at all; put the work in a provider the controller injects.

An error raised by a provider hook names the token the instance was built for, so a failing hook can be traced back to the declaration that registered it.

## Ordering

For module classes, Bustan walks the discovered module graph in root-first order during startup and in the reverse of that order during shutdown, so a root module is initialized before the modules it imports and torn down after them.

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
import asyncio

from bustan import Injectable, Module, create_app_context


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


async def main() -> None:
    context = create_app_context(AppModule)
    await context.init()
    await context.close()


asyncio.run(main())
```

```text
database module discovered
application ready
database connected
draining connections before shutdown (None)
application shutting down (None)
database disposed
```

The module hooks of one stage all run before the provider hooks of that stage, which is why `application ready` precedes `database connected` even though the pool is what the application is waiting for. Anything that must happen after a provider is live belongs in that provider's own hook rather than in a module's.

## `create_app()` Versus `create_app_context()`

- `create_app(AppModule)` compiles routes, constructs the HTTP adapter, and runs lifecycle stages through the platform lifespan.
- `create_app_context(AppModule)` builds only the DI application context. Call `await context.init()` to run startup hooks and `await context.close()` to run shutdown hooks.

That makes `ApplicationContext` useful for non-HTTP jobs, focused bootstrap tests, and integration helpers that need DI plus lifecycle but no server.

`init()` and `close()` are coroutines, so a script that is not already inside an event loop runs them through `asyncio.run`:

```python
import asyncio

from bustan import Injectable, Module, create_app_context


@Injectable()
class DatabasePool:
    def __init__(self) -> None:
        self.connected = False

    async def on_application_bootstrap(self) -> None:
        self.connected = True


@Module(providers=[DatabasePool])
class AppModule:
    pass


async def main() -> None:
    context = create_app_context(AppModule)
    await context.init()
    print("connected:", context.get(DatabasePool).connected)
    await context.close()


asyncio.run(main())
```

```text
connected: True
```

## Graceful Shutdown

A deployment replaces one process with another while callers are mid-request, so what a process does between being told to stop and exiting decides whether those callers see an answer or a dropped connection. `await app.listen(port)` installs that sequence for as long as it serves. On `SIGTERM` or `SIGINT`, in this order:

1. **Readiness turns negative.** The server stops admitting requests the moment the signal arrives. Anything that arrives from then on is answered `503 Service Unavailable` with a problem-details body, and the connection is closed with it, so a load balancer polling this process learns to route elsewhere rather than sending it work it will not finish.
2. **The requests already in flight are drained.** They keep running, and the shutdown waits for the last of them, for at most `drain_timeout` seconds.
3. **The teardown hooks run**, in the order the stages above describe, and are told the name of the signal that arrived.
4. **The listening port is released.** `listen()` returns once the server has let go of it, so the port can be bound again.

A request that outlasts the drain window is cancelled rather than waited on, because a shutdown that waited indefinitely is a shutdown one slow caller could refuse to allow. The window is `drain_timeout` seconds, ten by default:

```python
from bustan import Application


async def serve(app: Application) -> None:
    await app.listen(8000, drain_timeout=30.0)
```

`listen()` serves until the process is signalled or `close()` is called, so it is the last thing a program does rather than a step in the middle of one.

`await app.close()` runs exactly the same sequence for a caller rather than a signal: the server stops, in-flight requests drain, the hooks run with `signal` as `None`, and the call returns once the port is free. With no server running it is the teardown on its own, which is what `ApplicationContext.close()` has always been.

The drain belongs to the adapter, because only the adapter knows what its transport is serving. An adapter whose transport cannot report that is stopped and torn down as two steps instead, which is all it can promise.

## After Shutdown

Shutdown destroys the instances the application built, so it also drops them: the singleton, durable and controller caches are emptied once the last teardown stage has run.

Between that shutdown and the next startup the application resolves nothing. `context.get(token)`, `ModuleRef.get(token)` and every other resolution raises `ProviderResolutionError`, naming the token and saying the application must be started again. Building a replacement instead would hand back a provider whose `on_module_init` had never run - an unopened pool, an unconnected client - which is the failure the destroyed instance was dropped to avoid.

The rule is the same for every binding, including a transient provider and a `use_value` provider that run no initialization hook of their own. A transient provider reaches the destroyed singletons through its dependencies, so letting it through would rebuild them uninitialized and give back exactly what the refusal exists to prevent. Which kind of binding declares a token also belongs to the module that declares it and can change without its consumers being told, so a container that answered for some kinds and not others would make resolvability after shutdown a detail of somebody else's module.

Startup may then run again, and that is what lifts the refusal: it is lifted when the startup begins, because the startup stages resolve the providers whose hooks they run. A second `await context.init()`, or a second `with TestClient(app)` block over the same application, builds a fresh set of instances from the same module graph and runs every startup hook over them again. Overrides may be registered again in the same window, so the second startup can be given a different set from the first.

The graph, the container and the compiled routes are built once and are not rebuilt by a second startup; only the instances are.

## Failure Behavior

- Hook failures are wrapped in `LifecycleError`.
- A failing startup hook stops application bootstrap before the app starts serving traffic.
- A startup that fails part-way tears down whatever it had already built, in reverse construction order, before the failure propagates. The failure that reaches the caller is the one that stopped startup; a hook that also failed while undoing it is recorded as a note on that exception. The application is left closed, so a later `close()` does not run teardown a second time and resolution is refused until a startup succeeds.
- Every teardown stage runs to completion even when a hook fails, so one failing component cannot leak another component's resources.
- One failed teardown hook is raised on its own. More than one is raised together as an `ExceptionGroup`, which is also a `LifecycleError`; each member names the hook that failed and keeps the original exception as its `__cause__`.

If you need request-time cleanup or response shaping instead of process lifecycle behavior, use the request pipeline hooks described in [reference/request-pipeline.md](../reference/request-pipeline.md) instead.
