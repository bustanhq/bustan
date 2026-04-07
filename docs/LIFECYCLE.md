# Lifecycle Hooks

Module classes may define startup and shutdown hooks for application initialization and teardown.

## Supported Hook Names

- `on_module_init`
- `on_app_startup`
- `on_app_shutdown`
- `on_module_destroy`

Each hook may be synchronous or asynchronous.

## Ordering

- Startup runs `on_module_init` first, then `on_app_startup`, in `module_graph.nodes` order.
- Shutdown runs `on_app_shutdown` first, then `on_module_destroy`, in reverse module order.

## Example

```python
from bustan import Module


@Module()
class AppModule:
    def on_module_init(self) -> None:
        print("module init")

    async def on_app_startup(self) -> None:
        print("app startup")

    async def on_app_shutdown(self) -> None:
        print("app shutdown")

    def on_module_destroy(self) -> None:
        print("module destroy")
```

## Failure Behavior

- Hook failures are wrapped in `LifecycleError`.
- A failing startup hook stops application bootstrap.
- Shutdown follows the defined reverse-order teardown semantics for modules that were already started.