# Lifecycle Hooks

Modules and singleton providers can participate in application startup and shutdown. Bustan wires those lifecycle stages into the Starlette lifespan handler for HTTP applications, and `ApplicationContext` exposes the same semantics for non-HTTP bootstrapping.

## Supported Hook Names

- `on_module_init(self)`
- `on_application_bootstrap(self)`
- `before_application_shutdown(self, signal: str | None)`
- `on_application_shutdown(self, signal: str | None)`
- `on_module_destroy(self)`

Each hook may be synchronous or asynchronous.

## Ordering

For module classes, Bustan walks the discovered module graph in root-first order during startup and reverse order during shutdown.

Startup stages:

1. `on_module_init`
2. `on_application_bootstrap`

Shutdown stages:

1. `before_application_shutdown`
2. `on_application_shutdown`
3. `on_module_destroy`

Provider hooks run too. For a given stage, module hooks run first and singleton provider hooks run after the module stage completes. Shutdown stages run in reverse module order before provider teardown for that stage.

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

## Failure Behavior

- Hook failures are wrapped in `LifecycleError`.
- A failing startup hook stops application bootstrap before the app starts serving traffic.
- Shutdown still follows the reverse-order teardown semantics for stages that have already begun.

If you need request-time cleanup or response shaping instead of process lifecycle behavior, use the request pipeline hooks described in [REQUEST_PIPELINE.md](REQUEST_PIPELINE.md) instead.