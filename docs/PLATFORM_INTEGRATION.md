# Platform Integration

`Bustan` adds application structure on top of a platform adapter. The default adapter is Starlette, but the framework is designed so application code can stay mostly platform-neutral while still exposing the underlying engine when you need it.

## The Public `Application` Wrapper

`create_app()` returns an `Application`, not a raw Starlette app. The wrapper gives you both high-level runtime helpers and access to the underlying adapter.

Key public accessors:

- `app.get_http_server()` returns the underlying framework instance.
- `app.get_http_adapter()` returns the active adapter object.
- `app.container` exposes the DI container.
- `app.module_graph` exposes the discovered module graph.
- `app.root_module` returns the root module class.
- `app.root_key` returns the internal module-graph key for that root module.
- `app.route_contracts` and `app.execution_plans` expose compiled routing artifacts.

## Request Access

Handlers can depend on either the native Starlette request or the adapter-neutral `HttpRequest` wrapper.

Native Starlette request:

```python
from starlette.requests import Request

from bustan import Get


@Get("/{user_id}")
def read_user(self, request: Request, user_id: int) -> dict[str, object]:
	return {"path": request.url.path, "user_id": user_id}
```

Adapter-neutral request:

```python
from bustan import Get, HttpRequest


@Get("/{user_id}")
def read_user(self, request: HttpRequest, user_id: int) -> dict[str, object]:
	return {"path": request.path, "user_id": user_id}
```

## Response Control

If the default response coercion is not enough, return a platform response directly or use the adapter-neutral `HttpResponse`.

```python
from starlette.responses import PlainTextResponse

from bustan import Get, HttpResponse


@Get("/health")
def health(self) -> PlainTextResponse:
	return PlainTextResponse("ok", status_code=200)


@Get("/json")
def read_json(self) -> HttpResponse:
	return HttpResponse.json({"status": "ok"}, status_code=203)
```

## Configure The Underlying Platform

Use `app.get_http_server()` when a platform-specific feature is genuinely the right tool.

```python
app = create_app(AppModule)
server = app.get_http_server()

server.add_middleware(...)
server.mount("/static", static_app)
```

The `Application` wrapper also exposes helper methods for common platform integrations:

- `app.enable_cors(...)`
- `app.enable_swagger(...)`
- `await app.listen(...)`

## Runtime Artifacts And Inspection

Two public inspection helpers are especially useful in tests, governance tooling, and release validation:

- `app.snapshot_routes()` returns a deterministic route snapshot sorted by path and controller.
- `app.diff_routes(previous_snapshot)` compares a previous snapshot against the current route graph.

Example:

```python
previous = create_app(PreviousModule).snapshot_routes()
current = create_app(CurrentModule)
diff = current.diff_routes(previous)
```

Starlette server state also carries public runtime artifacts:

- `server.state.bustan_application`
- `server.state.bustan_container`
- `server.state.bustan_module_graph`
- `server.state.bustan_route_contracts`

## Discovery Support

For supported runtime introspection, import `DiscoveryModule` and inject `DiscoveryService` instead of reaching into private attributes.

```python
from bustan import Controller, DiscoveryModule, DiscoveryService, Get, Module


@Controller("/discovery")
class DiscoveryController:
	def __init__(self, discovery: DiscoveryService) -> None:
		self.discovery = discovery

	@Get("/")
	def read_discovery(self) -> dict[str, object]:
		return {
			"modules": [entry["module"] for entry in self.discovery.modules()],
			"routes": [entry["path"] for entry in self.discovery.routes()],
		}


@Module(imports=[DiscoveryModule], controllers=[DiscoveryController])
class AppModule:
	pass
```

## Non-HTTP Bootstrapping

Use `create_app_context()` when you want DI plus lifecycle behavior without an HTTP server. `ApplicationContext` supports `get()`, `resolve()`, `init()`, and `close()` but does not expose `listen()` or HTTP adapter access.