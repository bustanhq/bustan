# Platform Integration

`Bustan` adds application structure on top of a transport adapter. The framework compiles routes, resolves providers and executes handlers; the adapter carries requests in and responses out. Application code can stay entirely neutral about which adapter is underneath, and can reach through to the transport's own objects where a transport-specific feature is genuinely the right tool.

## The Adapter Port

The seam between the two is `bustan.contracts`. Everything an adapter needs is declared there and nowhere else, and nothing in it names a transport, so an adapter can be written against that module alone.

An adapter subclasses `AbstractHttpAdapter`, sets `name` and `capabilities`, and implements:

| Method | What it does |
| --- | --- |
| `from_native_request` | Wraps one request from this transport in the neutral `HttpRequest`. |
| `to_native_response` | Converts a framework response into what this transport writes. |
| `register_routes` | Registers the compiled `AdapterRoute` values it was handed, in order. |
| `start` / `stop` | Serves until stopped, and shuts down releasing what it holds. |
| `create_test_client` | Returns a client that drives it in process, without a socket. |
| `get_instance` | Returns the underlying server object it drives. |
| `add_middleware` | Wraps the whole server in one of the transport's own middleware classes. |

An adapter is never handed the dependency injection container, a compiled execution plan or a middleware registry. Those belong to the framework, and an adapter that received them would have to understand them.

`capabilities` is an `AdapterCapabilities` value stating what the transport can serve: host routing, raw body access, streaming responses, websocket upgrades. The framework checks each route's requirements against it while routes are compiled, so an adapter that cannot serve a route says so at startup rather than at the first request that needs the missing capability. The refusals are listed under [`RouteDefinitionError`](../reference/errors.md#routedefinitionerror).

## The Two Shipped Adapters

| Adapter | Import | Needs | Notes |
| --- | --- | --- | --- |
| Starlette | `bustan.adapters.starlette` | the `starlette` extra | The default. Serves through Uvicorn, and is the one `app.listen()` drains gracefully on a signal. |
| Raw ASGI | `bustan.adapters.asgi` | nothing beyond the framework | No third-party web framework at all. Used to prove the port is real, and to serve an application installed without the extra. |

`create_app(AppModule)` with no `adapter=` argument serves through the Starlette adapter, so `uv add bustan` on its own is not enough to serve HTTP; `uv add 'bustan[starlette]'` is. Pass `adapter=` a built adapter to serve through that one as it stands, or a callable, which the framework calls with an `AdapterRuntime` carrying `debug` and the lifespan that starts and stops the module graph.

Both adapters are held to the same conformance suite, and `scripts/conformance_matrix.py` runs it over both and fails when they answer any case differently. That comparison, rather than the existence of the port, is what makes "the transport is replaceable" a fact about this repository.

## The Public `Application` Wrapper

`create_app()` returns an `Application`, not a raw transport application. The wrapper gives you both high-level runtime helpers and access to the underlying adapter.

Key public accessors:

- `app.get_http_server()` returns the underlying server object.
- `app.get_http_adapter()` returns the active adapter object.
- `app.container` exposes the DI container.
- `app.module_graph` exposes the discovered module graph.
- `app.root_module` returns the root module class.
- `app.root_key` returns the internal module-graph key for that root module.
- `app.route_contracts` and `app.execution_plans` expose compiled routing artifacts.

## Request Access

Handlers can depend on either the transport's own request object or the adapter-neutral `HttpRequest`. The neutral one returns neutral values throughout: `request.url` is a `bustan.contracts.Url`, `request.query_params` a `QueryParams`, `request.headers` a case-insensitive `Headers`, and `request.state` an open per-request namespace. `request.native_request` is the declared way back to the transport's own object when you decide you want it.

Prefer the neutral one, and read the next section before writing the other.

Adapter-neutral request:

```python
from typing import Any, cast

from bustan import Controller, Get, HttpRequest, Module, create_app
from bustan.testing import AsgiTestClient


@Controller("/users")
class UsersController:
    @Get("/{user_id}")
    def read_user(self, request: HttpRequest, user_id: int) -> dict[str, object]:
        return {"path": request.path, "user_id": user_id}


@Module(controllers=[UsersController])
class AppModule:
    pass


with AsgiTestClient(cast(Any, create_app(AppModule))) as client:
    print(client.get("/users/7").json())
```

```text
{'path': '/users/7', 'user_id': 7}
```

The transport's own request:

```python
from typing import Any, cast

from starlette.requests import Request

from bustan import Controller, Get, Module, create_app
from bustan.testing import AsgiTestClient


@Controller("/users")
class UsersController:
    @Get("/{user_id}")
    def read_user(self, request: Request, user_id: int) -> dict[str, object]:
        return {"path": request.url.path, "user_id": user_id}


@Module(controllers=[UsersController])
class AppModule:
    pass


with AsgiTestClient(cast(Any, create_app(AppModule))) as client:
    print(client.get("/users/7").json())
```

```text
{'path': '/users/7', 'user_id': 7}
```

### A Native Annotation Names The Adapter That Serves It

A parameter annotated with a transport's own request type is handed `request.native_request` - the object the serving adapter built - so the annotation is true only when the adapter serving that route is the one that builds that type. The framework checks exactly that, and it checks it while the application is assembled.

The reading happens in two steps, because neither answers the whole question alone.

**Shape** says the parameter asked for a transport's request rather than the neutral one: the annotation must be a class carrying the whole of the internal native-request protocol - a body reachable as a stream, as bytes and as parsed JSON. `HttpRequest` carries no way to stream a body, which is what keeps the two spellings apart.

**Identity** says *which* transport. Every transport's request object has the same shape, so shape cannot tell one from another. Each adapter declares the type it produces - `AbstractHttpAdapter.native_request_type`, the counterpart of `from_native_request` - and the annotation is satisfied when the object that adapter hands over is an instance of what the parameter asked for. The Starlette adapter produces `starlette.requests.Request`; the raw ASGI adapter produces `AsgiHttpRequest`, which is its own request object because raw ASGI defines none.

A parameter the serving adapter cannot satisfy is refused with `RouteDefinitionError` when the routes are compiled, before any server starts. That is where it belongs: the mismatch is a property of how the application was wired rather than of any one request, and refusing it per request would turn a wiring error into a failure on every call.

```python
from typing import Any, cast

from starlette.requests import Request

from bustan import Controller, Get, Module, RouteDefinitionError, create_app
from bustan.adapters.asgi import AsgiAdapter, AsgiHttpRequest
from bustan.testing import AsgiTestClient


@Controller("/users")
class ItsOwnRequestController:
    @Get("/own")
    def own(self, request: AsgiHttpRequest) -> dict[str, object]:
        return {"handed": type(request).__name__, "path": request.path}


@Controller("/users")
class AnotherTransportsRequestController:
    @Get("/other")
    def other(self, request: Request) -> dict[str, object]:
        return {"handed": type(request).__name__}


def serve(controller: type[object]) -> Any:
    module = Module(controllers=[controller])(type("AppModule", (), {}))
    return create_app(module, adapter=lambda runtime: AsgiAdapter(lifespan=runtime.lifespan))


with AsgiTestClient(cast(Any, serve(ItsOwnRequestController))) as client:
    print(client.get("/users/own").json())

try:
    serve(AnotherTransportsRequestController)
except RouteDefinitionError as refusal:
    print(refusal)
```

```text
{'handed': 'AsgiHttpRequest', 'path': '/users/own'}
__main__.AnotherTransportsRequestController.other parameter 'request' names starlette.requests.Request, which AsgiAdapter does not produce: it produces bustan.adapters.asgi.requests.AsgiHttpRequest. Annotate HttpRequest and reach for request.native_request, or serve this application through the adapter whose request type the parameter names.
```

An annotation naming a transport is therefore a statement about the deployment that the framework will hold you to. Write it where the application genuinely serves on that transport and you want its object; the refusal is what stops it from quietly becoming false when the adapter changes.

One native spelling stays true under every adapter: `bustan.contracts.NativeHttpRequest`, the protocol itself. Every adapter's request satisfies it, so a handler that wants the transport's own object without naming a transport can write that instead of naming one.

Where you do not need the transport's object, write `HttpRequest` and reach for `request.native_request` at the point you want it. That is the spelling that never has to be re-checked when the adapter changes.

## Response Control

If the default response coercion is not enough, return the adapter-neutral `HttpResponse`, or a response the transport itself defines.

```python
from typing import Any, cast

from starlette.responses import PlainTextResponse

from bustan import Controller, Get, HttpResponse, Module, create_app
from bustan.testing import AsgiTestClient


@Controller("/")
class StatusController:
    @Get("/health")
    def health(self) -> PlainTextResponse:
        return PlainTextResponse("ok", status_code=200)

    @Get("/json")
    def read_json(self) -> HttpResponse:
        return HttpResponse.json({"status": "ok"}, status_code=203)


@Module(controllers=[StatusController])
class AppModule:
    pass


with AsgiTestClient(cast(Any, create_app(AppModule))) as client:
    print(client.get("/health").text, client.get("/json").status_code)
```

```text
ok 203
```

`HttpResponse` is the portable half of that pair. A `PlainTextResponse` is handed to the Starlette adapter unchanged and is meaningless to any other, so a route returning one is a route bound to that transport.

## Runtime Artifacts And Inspection

Two public inspection helpers are especially useful in tests, governance tooling, and release validation:

- `app.snapshot_routes()` returns a deterministic route snapshot sorted by path and controller.
- `app.diff_routes(previous_snapshot)` compares a previous snapshot against the current route graph.

A snapshot is a tuple of plain dictionaries, and a diff is a tuple of change records, each naming what changed and carrying the route as it was and as it is:

```python
from bustan import Controller, Get, Module, create_app


@Controller("/reports")
class ReportsController:
    @Get("/")
    def index(self) -> dict[str, str]:
        return {}

    @Get("/{report_id}")
    def read(self, report_id: int) -> dict[str, int]:
        return {"report_id": report_id}


@Module(controllers=[ReportsController])
class AppModule:
    pass


application = create_app(AppModule)
for route in application.snapshot_routes():
    print(route["method"], route["path"], route["controller"] + "." + route["handler"])

# Diffing against an empty snapshot reports every route as added; in a release check the
# previous snapshot is the one recorded for the last release.
for change in application.diff_routes(()):
    print(change["change"], change["route"], change["fields"])
```

```text
GET /reports ReportsController.index
GET /reports/{report_id} ReportsController.read
added ReportsController.index []
added ReportsController.read []
```

A change record's `fields` names the members that differ when a route was `changed` rather than added or removed, so a snapshot check reports what moved rather than only that something did.

The framework also keeps its own typed per-request slots on `request.slots`, which is where a stage that writes something for a later stage to read puts it. `slots.rate_limit` carries the throttler's decision for the response writer and the exception filter to read back.

The server object an adapter drives also carries public runtime artifacts, under `server.state`:

- `server.state.bustan_application`
- `server.state.bustan_container`
- `server.state.bustan_module_graph`
- `server.state.bustan_route_contracts`

## Discovery Support

For supported runtime introspection, import `DiscoveryModule` and inject `DiscoveryService` instead of reaching into private attributes. `DiscoveryModule` also exports `ModuleRef`, so importing it is one way to give a class a request-aware provider lookup.

```python
from typing import Any, cast

from bustan import Controller, DiscoveryModule, DiscoveryService, Get, Module, create_app
from bustan.testing import AsgiTestClient


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


with AsgiTestClient(cast(Any, create_app(AppModule))) as client:
    print(client.get("/discovery/").json())
```

```text
{'modules': ['AppModule', 'DiscoveryModule'], 'routes': ['/discovery']}
```

A route's compiled path carries no trailing slash: `@Controller("/discovery")` plus `@Get("/")` is the single path `/discovery`, which is what a snapshot, a diff and `bustan routes` all report.

## Where That Material Went

Reaching the underlying platform object, and bootstrapping without HTTP, are in [Configure The Underlying Platform](../how-to/configure-the-platform.md).
