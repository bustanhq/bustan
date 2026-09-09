# API Reference

This document is generated from docstrings in the stable public modules.
Regenerate it with `uv run python scripts/generate_api_reference.py`.

Stable modules:
- `bustan`
- `bustan.testing`
- `bustan.errors`

The `Defined in ...` lines identify implementation origins for browsing only.
Import supported symbols from the stable modules above, not from those internal paths.

## `bustan`

Bustan – A dependency injection framework for building modular Starlette applications.

### Import

```python
from bustan import __version__, Controller, create_app, Get, Injectable, Module
from bustan import ExceptionFilter, Guard, Interceptor, Pipe
```

### Exports

#### `__version__`

Installed distribution version string for the bustan package.

Runtime behavior: resolved from the installed distribution metadata, or from local project metadata when running from a source checkout.

#### `AbstractHttpAdapter`

```python
class AbstractHttpAdapter(ABC)
```

Defined in `bustan.contracts.adapter`.

Base class every transport adapter implements.

Subclasses set ``name`` to the transport they bind and ``capabilities`` to what
that transport can serve. Nothing here is handed the dependency injection
container, a compiled execution plan or a middleware registry: those belong to the
framework, and an adapter that received them would have to understand them.

##### Methods

- `from_native_request(self, native_request: object) -> HttpRequest`
  Wrap one request from this transport in the neutral request contract.
- `to_native_response(self, response: object) -> object`
  Convert a framework response into what this transport writes.

The argument is an :data:`HttpResponseValue`, or a response object this
transport itself produced because a handler returned one, which is returned
unchanged.
- `register_routes(self, routes: Sequence[AdapterRoute]) -> None`
  Register compiled routes with the underlying server, in the order given.
- `start(self, port: int, host: str = '127.0.0.1', reload: bool = False, **options: object) -> None`
  Serve requests until the server stops, binding ``host`` and ``port``.
- `stop(self) -> None`
  Shut the server down and release what it holds. Doing so twice is safe.
- `create_test_client(self) -> object`
  Return a client that drives this adapter in process, without a socket.

The client is the transport's own, because that is the client its users
already know how to drive; a conformance suite asks each adapter for one
rather than assuming any single library.
- `get_instance(self) -> object`
  Return the underlying server object this adapter drives.
- `add_middleware(self, middleware_class: type, **options: object) -> None`
  Wrap the whole server in one of the transport's own middleware classes.
- `listen(self, port: int, host: str = '127.0.0.1', reload: bool = False, **options: object) -> None`
  Serve requests, under the name the application wrapper calls.

This exists so that one verb reaches the server from the application object and
another from the port itself; both run :meth:`start`, which is the one an
adapter implements.

#### `AdapterCapabilities`

```python
class AdapterCapabilities
```

Defined in `bustan.contracts.adapter`.

What one transport adapter can and cannot do.

The framework checks a route's requirements against these before compiling it, so
an adapter that cannot serve a route says so at startup rather than at the first
request that needs the missing capability.

#### `AdapterRoute`

```python
class AdapterRoute
```

Defined in `bustan.contracts.adapter`.

One route for an adapter to register, described without naming a transport.

An adapter registers ``handler`` at ``path`` for every method in ``methods``, and
for each request calls ``from_native_request``, awaits ``handler``, then calls
``to_native_response`` on the result. Every route carries a handler, and there is
no way to hand an adapter a route already built in its own transport's terms, so
an adapter never has to recognise an opaque object as one of its own. A route that
reaches an adapter without a handler is a fault in the framework, and the adapter
refuses it by name rather than registering something that cannot serve a request.

``requires_raw_body``, ``requires_streaming`` and ``hosts`` restate what the route
needs from the transport, so the capability check reads the plan rather than
reaching back into the compiled contracts.

``attributes`` are names and values the adapter sets on whatever it registers. The
framework uses them to leave the compiled contract beside the route, so that
tooling reading a running server's routes back finds what produced each one; an
adapter that cannot carry them sets none and loses only that introspection.

#### `AdapterRuntime`

```python
class AdapterRuntime
```

Defined in `bustan.runtime.adapter`.

What the framework settled before an adapter existed, for the adapter to honour.

Two things about a run are the framework's to decide and an adapter's to apply, and
neither can be discovered from the port's methods. ``debug`` is how the deployment
was started. ``lifespan`` is the handler that starts and stops the module graph, so
an adapter that does not run it serves requests against modules whose ``on_startup``
never fired.

#### `Application`

```python
class Application(ApplicationContext)
```

Defined in `bustan.app.application`.

A high-level application wrapper for HTTP services.

This class extends the ApplicationContext with an HTTP server instance managed
via an AbstractHttpAdapter.

##### Methods

- `get_http_adapter(self) -> AbstractHttpAdapter`
  Accessor for the underlying HTTP framework adapter.
- `get_http_server(self) -> Any`
  Accessor for the underlying framework instance (e.g., Starlette App).
- `(property) route_contracts`
  Accessor for the compiled route contracts registered on the app.
- `(property) execution_plans`
  Accessor for the compiled route execution plans registered on the app.
- `snapshot_routes(self) -> tuple[dict[str, object], ...]`
  Return a deterministic snapshot of the compiled application routes.
- `diff_routes(self, previous_snapshot: Sequence[Mapping[str, object]]) -> tuple[dict[str, object], ...]`
  Compare a previous route snapshot against the current application routes.
- `enable_cors(self, options: CorsOptions | None = None) -> None`
  Register Starlette's CORS middleware on the application.
- `enable_swagger(self, path: str, document: dict[str, object], *, swagger_ui_path: str | None = None) -> None`
  Register OpenAPI JSON and Swagger UI routes.
- `listen(self, port: int, host: str = '127.0.0.1', reload: bool = False, *, drain_timeout: float | None = None, **kwargs: Any) -> None`
  Serve the application until the server is signalled or stopped.

A ``SIGINT`` or a ``SIGTERM`` arriving while this is serving stops the server
gracefully. New requests are refused while the requests already in flight are
given ``drain_timeout`` seconds to finish, then the shutdown hooks run and are
told which signal arrived, and only then is the listening port released. A
request that outlasts the window is cancelled rather than allowed to hold the
process open. Left out, ``drain_timeout`` is whatever the adapter was built
with; an adapter whose transport cannot drain serves and stops as before.
- `close(self) -> None`
  Stop the server, if one is running, and run the application shutdown sequence.

A running server is stopped the way a signal stops it, and this returns once it
has released its port, so a caller may bind that port again or start the
application afresh. With no server running there is nothing to drain and this is
the teardown on its own.
- `(property) routes`
  Accessor for the registered routes (by path).

#### `ApplicationContext`

```python
class ApplicationContext
```

Defined in `bustan.app.application`.

A standalone application context for dependency injection.

This provides a clean interface for resolving services from the Bustan
IoC container, without an associated HTTP server instance.

##### Methods

- `(property) container`
  Accessor for the underlying dependency injection container.
- `(property) module_graph`
  Accessor for the discovered module graph.
- `(property) root_module`
  Accessor for the application's root module class.
- `(property) root_key`
  Accessor for the application's root module key (ModuleKey).
- `(property) lifecycle_manager`
  Accessor for the manager that runs startup and shutdown, if there is one.

A context built without one never runs a lifecycle hook, so `init()` and
`close()` on it do nothing.
- `(property) http_application`
  Accessor for the HTTP application assembled around this context.

A context created on its own serves no HTTP traffic and has none, which is how
a caller tells the two apart without inspecting either.
- `get(self, token: object) -> Any`
  Resolve a provider as though no request were being served.

The token types what comes back: a class yields an instance of itself, and an
``InjectionToken[T]`` yields a ``T``. Either way, assigning the result to
something else is a type error rather than something a cast has to assert. A
token that carries no type - a bare string, an enum member - names nothing a
checker can read, so resolving through one is unchecked.

Anything scoped to a request is refused here, whether or not a request happens
to be in flight, so a provider resolved this way can never capture one caller's
state and hand it to the next. To reach a request-scoped provider from inside a
handler, a guard or an interceptor, inject `ModuleRef` and call its `get()`:
that resolves against the request currently being served.
- `resolve(self, token: object) -> Any`
  Alias for app.get(), with the same non-request semantics and the same typing.
- `init(self) -> ApplicationContext`
  Initialize asynchronous providers and lifecycle hooks.

The application is the running application for the whole of startup, so a
provider built eagerly here may inject `APPLICATION` exactly as one built
lazily during a request can.
- `close(self) -> None`
  Run the application shutdown sequence, destroying what startup built.

A context serves no HTTP traffic, so there is nothing to drain and nothing that
asked it to stop: the teardown hooks run immediately and receive no signal name.

#### `APPLICATION`

Defined in `bustan.kernel.ioc.tokens`.

A typed token representing a dependency for injection.

A token is its own identity: two tokens are the same token only when they are the
same object, so build each one once at module level and import it wherever it is
declared, injected or overridden. The name is what the token is called in errors;
the container never matches two tokens by comparing names.

Current value: `InjectionToken('APPLICATION')`

#### `APP_FILTER`

Defined in `bustan.kernel.ioc.tokens`.

A typed token representing a dependency for injection.

A token is its own identity: two tokens are the same token only when they are the
same object, so build each one once at module level and import it wherever it is
declared, injected or overridden. The name is what the token is called in errors;
the container never matches two tokens by comparing names.

Current value: `InjectionToken('APP_FILTER')`

#### `APP_GUARD`

Defined in `bustan.kernel.ioc.tokens`.

A typed token representing a dependency for injection.

A token is its own identity: two tokens are the same token only when they are the
same object, so build each one once at module level and import it wherever it is
declared, injected or overridden. The name is what the token is called in errors;
the container never matches two tokens by comparing names.

Current value: `InjectionToken('APP_GUARD')`

#### `APP_INTERCEPTOR`

Defined in `bustan.kernel.ioc.tokens`.

A typed token representing a dependency for injection.

A token is its own identity: two tokens are the same token only when they are the
same object, so build each one once at module level and import it wherever it is
declared, injected or overridden. The name is what the token is called in errors;
the container never matches two tokens by comparing names.

Current value: `InjectionToken('APP_INTERCEPTOR')`

#### `APP_PIPE`

Defined in `bustan.kernel.ioc.tokens`.

A typed token representing a dependency for injection.

A token is its own identity: two tokens are the same token only when they are the
same object, so build each one once at module level and import it wherever it is
declared, injected or overridden. The name is what the token is called in errors;
the container never matches two tokens by comparing names.

Current value: `InjectionToken('APP_PIPE')`

#### `ArgumentsHost`

```python
class ArgumentsHost
```

Defined in `bustan.pipeline.context`.

Public wrapper around transport arguments passed through the pipeline.

##### Methods

- `get_args(self) -> tuple[object, ...]`
- `get_arg_by_index(self, index: int) -> object | None`
- `get_type(self) -> Literal['http']`
- `switch_to_http(self) -> HttpArgumentsHost`

#### `CallHandler`

```python
class CallHandler(Protocol)
```

Defined in `bustan.pipeline.interceptors`.

Public continuation contract for interceptor chaining.

##### Methods

- `handle(self) -> object`
  Resume the next link in the interceptor chain.

#### `ApiBearerAuth`

```python
def ApiBearerAuth(name: str = 'bearer') -> Callable[[DecoratedT], DecoratedT]
```

Defined in `bustan.openapi.decorators`.

No user-facing documentation provided.

#### `ApiBody`

```python
def ApiBody(*, type: type[object], description: str = '') -> Callable[[DecoratedT], DecoratedT]
```

Defined in `bustan.openapi.decorators`.

No user-facing documentation provided.

#### `ApiOperation`

```python
def ApiOperation(*, summary: str = '', description: str = '') -> Callable[[DecoratedT], DecoratedT]
```

Defined in `bustan.openapi.decorators`.

No user-facing documentation provided.

#### `ApiParam`

```python
def ApiParam(*, name: str, description: str = '', required: bool = True) -> Callable[[DecoratedT], DecoratedT]
```

Defined in `bustan.openapi.decorators`.

No user-facing documentation provided.

#### `ApiQuery`

```python
def ApiQuery(*, name: str, description: str = '', required: bool = False, type: type[object] = <class 'str'>) -> Callable[[DecoratedT], DecoratedT]
```

Defined in `bustan.openapi.decorators`.

No user-facing documentation provided.

#### `ApiResponse`

```python
def ApiResponse(*, status: int, description: str = '', schema: type[object] | None = None) -> Callable[[DecoratedT], DecoratedT]
```

Defined in `bustan.openapi.decorators`.

No user-facing documentation provided.

#### `ApiTags`

```python
def ApiTags(*tags: str) -> Callable[[DecoratedT], DecoratedT]
```

Defined in `bustan.openapi.decorators`.

No user-facing documentation provided.

#### `Audit`

```python
def Audit(*, event: str) -> Callable[[DecoratedT], DecoratedT]
```

Defined in `bustan.security.policy`.

No audit record is written in this version; the decorator only records the policy.

``event`` reaches the route's compiled policy plan, and nothing in the request path
acts on it, so a route marked with this decorator leaves no trace of who called it.
Write the record from the handler, or from an interceptor of your own, for as long
as that is so.

#### `Auth`

```python
def Auth(strategy: str) -> Callable[[DecoratedT], DecoratedT]
```

Defined in `bustan.security.policy`.

Serve this route only to a caller the named authentication strategy identifies.

``strategy`` selects one authenticator out of the registry a module binds under
``AUTHENTICATOR_REGISTRY``. It runs before the handler, and the principal it
returns is what ``Roles`` and ``Permissions`` are then checked against. A caller it
does not identify is refused with the challenge that says how to present an
identity. A strategy the registry does not name refuses every caller of the route
whatever it sends, so it is reported as an application fault rather than as a
refusal of the caller, and the reason is written to the log rather than to them.

#### `AUTHENTICATOR_REGISTRY`

Defined in `bustan.kernel.ioc.tokens`.

A typed token representing a dependency for injection.

A token is its own identity: two tokens are the same token only when they are the
same object, so build each one once at module level and import it wherever it is
declared, injected or overridden. The name is what the token is called in errors;
the container never matches two tokens by comparing names.

Current value: `InjectionToken('AUTHENTICATOR_REGISTRY')`

#### `Authenticator`

```python
class Authenticator(Protocol)
```

Defined in `bustan.pipeline.auth`.

Identifies the caller behind one request, answering None when it cannot.

##### Methods

- `authenticate(self, context: ExecutionContext) -> Principal | None`

#### `BadRequestException`

```python
class BadRequestException(HttpException)
```

Defined in `bustan.kernel.errors`.

Raised when a request fails explicit validation.

The message reaches the caller, because it is about the request that was just
sent: which field was wrong, where it was read from and what was expected there.

##### Methods

- `to_payload(self) -> dict[str, str]`

#### `Body`

Defined in `bustan.common.decorators.parameter`.

Makes a marker usable both bare (``Annotated[str, Body]``)
and as a call (``Annotated[str, Body("field")]``).

Current value: `Body`

#### `BeforeApplicationShutdown`

```python
class BeforeApplicationShutdown(Protocol)
```

Defined in `bustan.kernel.lifecycle.hooks`.

Protocol for components that run before application shutdown begins.

##### Methods

- `before_application_shutdown(self, signal: str | None) -> None | Awaitable[None]`

#### `Cookies`

Defined in `bustan.common.decorators.parameter`.

Makes a marker usable both bare (``Annotated[str, Body]``)
and as a call (``Annotated[str, Body("field")]``).

Current value: `Cookies`

#### `create_app`

```python
def create_app(root_module: type[object] | DynamicModule, *, debug: bool = False, adapter: AbstractHttpAdapter | AdapterFactory | None = None, pipeline_override_registry: PipelineOverrideRegistry | None = None, versioning: VersioningOptions | None = None, swagger: SwaggerOptions | None = None, observability: ObservabilityHooks | None = None, request_limits: RequestLimits | None = None, response_serializer: ResponseSerializer | None = None) -> Application
```

Defined in `bustan.app.bootstrap`.

Create a fully assembled Bustan application from the root module.

``adapter`` chooses the transport. Left out, the application serves through the
Starlette adapter, which needs the ``starlette`` extra installed. Given a built
adapter, that adapter serves as it stands. Given a callable, the framework calls it
with an :class:`AdapterRuntime` and serves through what it returns, which is how an
adapter other than the default is handed ``debug`` and the lifespan that starts and
stops the module graph.

``observability`` attaches a metrics backend and a tracer. Build it with the sinks
you have - ``ObservabilityHooks(metrics=..., tracer=...)`` - and every request this
application serves is counted, timed and traced through them. The hooks belong to
this application rather than to the process, so a second application in the same
process can report somewhere else. Left out, requests are still measured and still
correlated; there is simply nothing listening.

``request_limits`` chooses what this application will spend on a single request:
how many body bytes it reads, how many uploaded parts it binds, how long it runs
and how many synchronous handlers it runs at once. Build it with the bounds you
have measured - ``RequestLimits(max_body_bytes=...)`` - and a request over one of
them is refused with the status the limit implies rather than served. The limits
belong to this application rather than to the process, so a second application in
the same process can serve under different ones. Left out, requests are served
under bounds that are finite already; there is no way to end up with none.

``response_serializer`` decides what a handler's return value becomes on the wire.
Implement ``ResponseSerializer`` - one ``serialize(value)`` method returning an
``HttpResponse`` - and every route that returns a value rather than a response of
its own is written through it, so an application can render its own types without
each handler building a response by hand. Delegate to ``DefaultResponseSerializer``
for the values you do not handle. It applies to the values the framework serializes,
not to a handler that streams, returns a file or returns a response already built.
The serializer belongs to this application rather than to the process, so a second
application in the same process can render differently. Left out, values are
serialized as they are today.

#### `create_app_context`

```python
def create_app_context(root_module: type[object] | DynamicModule) -> ApplicationContext
```

Defined in `bustan.app.bootstrap`.

Create a standalone application context for dependency injection.

#### `create_param_decorator`

```python
def create_param_decorator(factory: Callable[[object | None, object], object | Awaitable[object]], *, name: str | None = None) -> _CustomParameterDecorator
```

Defined in `bustan.common.decorators.parameter`.

Create an ``ExecutionContext``-backed custom parameter decorator.

#### `BustanError`

```python
class BustanError(Exception)
```

Defined in `bustan.kernel.errors`.

Base exception for the framework.

#### `Cache`

```python
def Cache(*, ttl: int) -> Callable[[DecoratedT], DecoratedT]
```

Defined in `bustan.security.policy`.

No response is cached in this version; the decorator only records the policy.

``ttl`` reaches the route's compiled policy plan, and nothing in the request path
acts on it, so a route marked with this decorator is recomputed on every request.
Cache in front of the application, or inside the handler, for as long as that is so.

#### `ContextId`

```python
class ContextId
```

Defined in `bustan.addons.context`.

Stable scope-qualified context identifier.

#### `Controller`

```python
def Controller(prefix: str = '', *, scope: ProviderScope | str = ProviderScope.SINGLETON, version: str | list[str] | None = None, host: HostInput | None = None, hosts: HostInput | None = None, binding_mode: str = 'infer', validation_mode: str = 'auto', validate_custom_decorators: bool = False) -> Callable[[ClassT], ClassT]
```

Defined in `bustan.common.decorators.controller`.

Attach controller metadata to a class.

#### `DefaultResponseSerializer`

```python
class DefaultResponseSerializer
```

Defined in `bustan.runtime.responses`.

Serialize common Python values into adapter-neutral HTTP responses.

##### Methods

- `serialize(self, value: object) -> HttpResponse | NativeHttpResponse`

#### `Delete`

```python
def Delete(path: str = '/', *, version: str | list[str] | None = None, host: HostInput | None = None, hosts: HostInput | None = None) -> Callable[[FunctionT], FunctionT]
```

Defined in `bustan.common.decorators.route`.

Return a decorator that registers a DELETE route.

#### `DeprecatedRoute`

```python
def DeprecatedRoute(*, since: str | None = None, sunset: str | None = None, replacement: str | None = None) -> Callable[[DecoratedT], DecoratedT]
```

Defined in `bustan.security.policy`.

Record that this route is going away, and what its callers should move to.

``since`` is when it was deprecated, ``sunset`` when it stops being served and
``replacement`` what to call instead; all three are free text the framework only
carries. No response header is written from them and nothing in the request path
reads them, so a caller learns none of this from the route itself. They reach the
route's compiled policy plan, and the governance ownership report renders them for
whoever is planning the removal.

#### `DiscoveryModule`

```python
class DiscoveryModule
```

Defined in `bustan.addons.discovery`.

Addon module that exposes the read-only DiscoveryService.

#### `DiscoveryService`

```python
class DiscoveryService
```

Defined in `bustan.addons.discovery`.

Read-only inspection surface for compiled modules, providers, and routes.

##### Methods

- `modules(self) -> tuple[dict[str, object], ...]`
- `providers(self) -> tuple[dict[str, object], ...]`
- `providers_for_module(self, module: ModuleKey | type[object]) -> tuple[dict[str, object], ...]`
- `routes(self) -> tuple[dict[str, object], ...]`
  Return the compiled routes, or nothing when there is no HTTP runtime.

A standalone application context serves no routes, so there are none to report
rather than an error to raise.

#### `DurableProvider`

```python
class DurableProvider(Protocol)
```

Defined in `bustan.kernel.ioc.scopes`.

Protocol for providers that derive a durable cache key from the request.

##### Methods

- `get_durable_context_key(cls, request: HttpRequest | None) -> Hashable`

#### `DynamicModule`

```python
class DynamicModule
```

Defined in `bustan.kernel.module.dynamic`.

Metadata overlay that compiles into a unique module instance.

Two registrations that declare the same thing *are* the same registration: calling
``for_root(options)`` twice with the same options describes one module, not two,
and building both would give the application two copies of every provider inside
it and two sets of their singletons. Constructing one therefore returns the
registration that already describes those values whenever there is one, so identity
follows the declaration rather than the order the objects were created in.

What the overlay declares wins over the base module. A provider here replaces the
base module's provider for the same token, which is what lets a base module declare
a default and a registration configure it away; a global pipeline token is the one
exception, because a second declaration of one of those adds a component to a slot
that runs them all. An import or a controller the base module already names is one
entry rather than two, so naming it again here adds nothing and is not an error.

#### `DocumentBuilder`

```python
class DocumentBuilder
```

Defined in `bustan.openapi.document_builder`.

Fluent builder for the base OpenAPI document.

##### Methods

- `set_title(self, title: str) -> DocumentBuilder`
- `set_version(self, version: str) -> DocumentBuilder`
- `set_description(self, description: str) -> DocumentBuilder`
- `add_bearer_auth(self, name: str = 'bearer') -> DocumentBuilder`
- `build(self) -> dict[str, object]`

#### `ExecutionContext`

```python
class ExecutionContext(ArgumentsHost)
```

Defined in `bustan.pipeline.context`.

Public request execution context shared across guards and filters.

##### Methods

- `create_http(cls, *, request: HttpRequest | object, response: object | None, handler: object, controller_cls: type[object], module: ModuleKey, controller: object, container: Container, route: ControllerRouteDefinition | None = None, route_contract: object | None = None, policy_plan: object | None = None) -> ExecutionContext`
- `get_handler(self) -> object`
- `get_class(self) -> type[object]`
- `get_module(self) -> ModuleKey`
- `get_route_contract(self) -> object | None`
- `get_policy_plan(self) -> object | None`
- `get_principal(self) -> object | None`
- `with_parameter(self, *, name: str, source: str, annotation: object, value: object, validation_mode: str = 'auto', validate_custom_decorators: bool = False) -> ExecutionContext`
- `with_parameter_value(self, value: object) -> ExecutionContext`
- `(property) request`
- `(property) response`
- `(property) module`
- `(property) controller_type`
- `(property) controller`
- `(property) container`
- `(property) route`
- `(property) route_contract`
- `(property) policy_plan`
- `(property) parameter_name`
- `(property) parameter_source`
- `(property) parameter_annotation`
- `(property) parameter_value`
- `(property) name`
- `(property) source`
- `(property) annotation`
- `(property) value`
- `(property) validation_mode`
- `(property) validate_custom_decorators`
- `(property) metatype`
- `(property) execution_context`

#### `ExceptionFilter`

```python
class ExceptionFilter
```

Defined in `bustan.pipeline.filters`.

Base class for mapping exceptions to handler results.

Override exception_types to declare which exception classes this filter can
handle.

##### Attributes

- `exception_types`
  Default: `(<class 'Exception'>,)`
  Tuple of exception classes the filter handles.

##### Methods

- `catch(self, exc: Exception, context: ExecutionContext) -> object | Awaitable[object]`
  Convert an exception into a handler result or response payload.

#### `ExportViolationError`

```python
class ExportViolationError(InvalidModuleError)
```

Defined in `bustan.kernel.errors`.

Raised when a module exports a provider it does not declare.

#### `Get`

```python
def Get(path: str = '/', *, version: str | list[str] | None = None, host: HostInput | None = None, hosts: HostInput | None = None) -> Callable[[FunctionT], FunctionT]
```

Defined in `bustan.common.decorators.route`.

Return a decorator that registers a GET route.

#### `Global`

```python
def Global() -> Callable[[ClassT], ClassT]
```

Defined in `bustan.kernel.module.decorators`.

Promote an existing module declaration to a global module.

#### `Guard`

```python
class Guard
```

Defined in `bustan.pipeline.guards`.

Base class for authorization and policy gates.

##### Methods

- `can_activate(self, context: ExecutionContext) -> bool | Awaitable[bool]`
  Return True to allow request execution to continue.

#### `GuardRejectedError`

```python
class GuardRejectedError(BustanError)
```

Defined in `bustan.kernel.errors`.

Raised when a guard blocks request execution.

#### `Header`

Defined in `bustan.common.decorators.parameter`.

Makes a marker usable both bare (``Annotated[str, Body]``)
and as a call (``Annotated[str, Body("field")]``).

Current value: `Header`

#### `HealthIndicator`

```python
class HealthIndicator(Protocol)
```

Defined in `bustan.health.indicators`.

One question a probe asks about one dependency, and the name it answers under.

An implementation watches exactly one thing, so that a probe reporting ``down``
names which thing is down rather than only that something is. ``name`` is the key
its result appears under in the report and must be unique within a probe.

``check`` is allowed to fail, in every way an ``await`` can fail: it may raise, and
it may never return. Neither reaches the caller of the probe. A raise is recorded
as a down result under this indicator's name, and an indicator that does not answer
in time is recorded the same way, because a probe that one broken dependency can
crash or hang is worse than no probe at all: it gets the process killed for a fault
that was never the process's.

##### Methods

- `(property) name`
  Key this indicator's result is reported under, unique within one probe.
- `check(self) -> HealthIndicatorResult`
  Answer for the one dependency this indicator watches.

#### `HealthIndicatorResult`

```python
class HealthIndicatorResult
```

Defined in `bustan.health.indicators`.

What one indicator answered, and why it answered that.

``detail`` is one short sentence for whoever reads the probe. It crosses a trust
boundary, because anything that can reach the probe reads it, so it says what is
wrong in the framework's own words and never carries a host name, a connection
string, a credential, or the message of an exception raised inside a dependency.
It is ``None`` on a serving result that has nothing to add.

##### Methods

- `up(cls, detail: str | None = None) -> HealthIndicatorResult`
  Return a serving result, optionally saying something about it.
- `down(cls, detail: str) -> HealthIndicatorResult`
  Return a failing result, which must say why it failed.

#### `HealthModule`

```python
class HealthModule
```

Defined in `bustan.health.module`.

Factory for the health module: the probes, their routes, and the readiness state.

##### Methods

- `for_root(*, check_timeout: float = 5.0, is_global: bool = True) -> DynamicModule`
  Register the probe routes and export the service and the readiness state.

Global by default, because both of the things it exports are used from outside
the module that declared them: an indicator is registered by whichever module
owns the dependency it watches, and the readiness state is set by whatever owns
the shutdown sequence.

Register indicators by injecting ``HealthService`` and calling its register
methods from a module initialization hook. That stage runs before any hook can
report the application started, so an indicator registered there is already
being consulted the first time readiness can be true.

``check_timeout`` is how long any one indicator is given to answer before it is
recorded as down. Indicators are checked together, so it bounds the whole probe
however many are registered; keep it below the interval the probe is read on.

#### `HealthReport`

```python
class HealthReport
```

Defined in `bustan.health.indicators`.

The answer one probe gives, and the wire shape it serialises to.

``status`` is ``up`` only when every entry in ``checks`` is up, so a probe with no
indicators registered is up. ``checks`` keeps the order the indicators were
registered in, and the built-in lifecycle check of the readiness probe comes first.

``as_dict`` renders the documented response shape, and is what an HTTP endpoint
serialises. It is exactly two levels deep and has no optional keys: ``detail`` is
always present and is ``null`` when the check had nothing to add, so a reader never
has to tell a missing key from an absent detail::

    {
      "status": "down",
      "checks": {
        "lifecycle": {"status": "down", "detail": "startup has not completed"},
        "database": {"status": "up", "detail": null}
      }
    }

The shape carries no timing, no version and no host name. Those identify the
process to anything that can reach the probe, and none of them is needed to decide
whether to send it traffic.

##### Methods

- `as_dict(self) -> dict[str, object]`
  Render the documented response shape as plain JSON-serialisable data.

#### `HealthService`

```python
class HealthService
```

Defined in `bustan.health.service`.

Registers health indicators and answers the liveness and readiness probes.

The two probes answer different questions and share no indicators, because the two
answers cause different things to happen.

**Liveness** answers whether the process is alive, and the only honest evidence for
that is that it answered at all. It therefore starts up, and stays, with nothing
registered against it: no dependency belongs here, because a failing dependency is
not a reason to kill and restart a process that is working. Register a liveness
indicator only for a fault the process has detected in itself and cannot recover
from without being restarted.

**Readiness** answers whether this pod should be sent traffic. It always begins with
the built-in lifecycle check, which is down before startup finishes and down again
once the process is draining, and adds every dependency the process needs in order
to serve a request correctly. A readiness indicator going down takes one pod out of
rotation, which is recoverable; that is why the dependencies belong here.

Every indicator of a probe is checked on each read, and they are checked together,
so one slow dependency does not delay the answer about the others.

A registered indicator cannot take a probe down. One that raises, one that does not
answer within the check timeout, and one that answers with something that is not a
result are each recorded as a down check under their own name, and the probe still
reports on every other indicator. The failure is logged in full; what reaches the
caller of the probe names only the kind of failure, because anything that can reach
a probe reads its response.

##### Methods

- `register_liveness(self, indicator: HealthIndicator) -> None`
  Register an indicator for a fault only a restart can clear.

Registering a dependency here instead of on readiness is the mistake this
method exists to be deliberate about: it turns an outage in something else into
a restart of this process, which cannot fix it and loses everything in flight.
- `register_readiness(self, indicator: HealthIndicator) -> None`
  Register an indicator for something this process needs in order to serve.
- `liveness(self) -> HealthReport`
  Report whether the process is alive, consulting nothing about its lifecycle.

Startup and drain are deliberately invisible here. A process that is still
starting and a process that is draining are both alive, and reporting either as
dead is what turns a rolling deploy into a crash loop.
- `readiness(self) -> HealthReport`
  Report whether this process should be sent traffic.

Down until startup finishes, down again from the moment the process is asked to
stop, and down whenever a dependency it needs in order to serve is down.

#### `HealthStatus`

```python
class HealthStatus(StrEnum)
```

Defined in `bustan.health.indicators`.

Whether one check, or a whole probe, is serving.

Two values are the whole vocabulary because a probe is read by a machine that can
only route traffic or withhold it, so any third state would have to be collapsed
into one of these by whoever read it, and the collapse would be a guess. An
indicator with more to say says it in its detail.

#### `HostParam`

Defined in `bustan.common.decorators.parameter`.

Makes a marker usable both bare (``Annotated[str, Body]``)
and as a call (``Annotated[str, Body("field")]``).

Current value: `HostParam`

#### `HttpArgumentsHost`

```python
class HttpArgumentsHost
```

Defined in `bustan.pipeline.context`.

HTTP-specific view over a generic arguments host.

##### Methods

- `get_request(self) -> object | None`
- `get_response(self) -> object | None`
- `get_next(self) -> object | None`

#### `HttpFormData`

```python
class HttpFormData(Protocol)
```

Defined in `bustan.contracts.requests`.

Minimal form-data surface used by parameter binding.

##### Methods

- `get(self, key: str, default: object | None = None) -> object | None`
- `getlist(self, key: str) -> list[object]`

#### `HttpQueryParams`

```python
class HttpQueryParams(Protocol)
```

Defined in `bustan.contracts.requests`.

Minimal multi-value query parameter surface used by parameter binding.

##### Methods

- `getlist(self, key: str) -> list[str]`

#### `HttpRequest`

```python
class HttpRequest(Protocol)
```

Defined in `bustan.contracts.requests`.

Adapter-neutral request surface used by framework runtime code.

##### Methods

- `(property) native_request`
- `(property) method`
- `(property) path`
- `(property) url`
- `(property) headers`
- `(property) query_params`
- `(property) path_params`
- `(property) cookies`
- `(property) state`
- `(property) slots`
- `(property) client`
- `(property) app`
- `body(self) -> bytes`
- `json(self) -> object`
- `form(self) -> HttpFormData`

#### `HttpResponse`

```python
class HttpResponse
```

Defined in `bustan.contracts.responses`.

Adapter-neutral mutable HTTP response container.

##### Methods

- `set_body(self, body: bytes | str) -> None`
  Replace the body, encoding text as UTF-8.
- `send(self, body: bytes | str) -> None`
  Replace the body from an awaiting caller; the response is written later.
- `empty(cls, *, status_code: int = 204) -> HttpResponse`
  Return a response with no body, defaulting to ``204 No Content``.
- `json(cls, payload: object, *, status_code: int = 200, headers: Mapping[str, str] | None = None) -> HttpResponse`
  Return a JSON response serialised without insignificant whitespace.

#### `HttpUrl`

```python
class HttpUrl(Protocol)
```

Defined in `bustan.contracts.requests`.

Minimal URL surface required by the framework runtime.

##### Methods

- `(property) path`

#### `Idempotent`

```python
def Idempotent(*, key_header: str = 'Idempotency-Key') -> Callable[[DecoratedT], DecoratedT]
```

Defined in `bustan.security.policy`.

No idempotency key is stored or compared in this version; the policy is recorded.

``key_header`` reaches the route's compiled policy plan, and nothing in the request
path acts on it, so a retried request runs the handler again and its side effect
happens again. Deduplicate inside the handler, against the store that already holds
the side effect, for as long as that is so.

#### `Inject`

```python
def Inject(token: object) -> InjectMarker
```

Defined in `bustan.common.decorators.injectable`.

Mark an ``Annotated`` dependency to resolve from an explicit token.

#### `Injectable`

```python
def Injectable(target: ClassT | None = None, *, scope: ProviderScope | str = ProviderScope.SINGLETON) -> ClassT | Callable[[ClassT], ClassT]
```

Defined in `bustan.common.decorators.injectable`.

Mark a class as a DI-managed provider with the selected scope.

#### `INQUIRER`

Defined in `bustan.kernel.ioc.tokens`.

A typed token representing a dependency for injection.

A token is its own identity: two tokens are the same token only when they are the
same object, so build each one once at module level and import it wherever it is
declared, injected or overridden. The name is what the token is called in errors;
the container never matches two tokens by comparing names.

Current value: `InjectionToken('INQUIRER')`

#### `InjectionToken`

```python
class InjectionToken(Generic)
```

Defined in `bustan.kernel.ioc.tokens`.

A typed token representing a dependency for injection.

A token is its own identity: two tokens are the same token only when they are the
same object, so build each one once at module level and import it wherever it is
declared, injected or overridden. The name is what the token is called in errors;
the container never matches two tokens by comparing names.

#### `Interceptor`

```python
class Interceptor
```

Defined in `bustan.pipeline.interceptors`.

Base class for around-handler behaviors.

##### Methods

- `intercept(self, context: ExecutionContext, next: CallHandler) -> object`
  Wrap handler execution and optionally transform the result.

#### `InvalidControllerError`

```python
class InvalidControllerError(BustanError)
```

Defined in `bustan.kernel.errors`.

Raised when a controller declaration is invalid.

#### `InvalidModuleError`

```python
class InvalidModuleError(BustanError)
```

Defined in `bustan.kernel.errors`.

Raised when module declarations or imports are invalid.

#### `InvalidPipelineError`

```python
class InvalidPipelineError(BustanError)
```

Defined in `bustan.kernel.errors`.

Raised when pipeline decorators or components are invalid.

#### `InvalidProviderError`

```python
class InvalidProviderError(BustanError)
```

Defined in `bustan.kernel.errors`.

Raised when a provider declaration is invalid.

#### `LifecycleError`

```python
class LifecycleError(BustanError)
```

Defined in `bustan.kernel.errors`.

Raised when application lifecycle hooks fail.

#### `LogLevel`

```python
class LogLevel(IntEnum)
```

Defined in `bustan.observability.logger`.

Enum where members are also (and must be) ints

#### `Logger`

```python
class Logger
```

Defined in `bustan.observability.logger`.

NestJS-style logger with context labels, level filtering and structured fields.

Every call emits exactly one record, whatever the message contains. A record
carries the time, the framework level, the context label, the message, the
correlation and trace ids of the request in flight when there is one, and whatever
structured ``fields`` the caller passed, with configured keys redacted.

An override installed with :meth:`override_logger` or :meth:`scoped_override`
replaces the destination for the context that installed it and for nothing else,
so a test that redirects records does not redirect another request's.

##### Methods

- `log(self, message: str, context: str | None = None) -> None`
- `warn(self, message: str, context: str | None = None) -> None`
- `error(self, message: str, trace: str | None = None, context: str | None = None) -> None`
- `debug(self, message: str, context: str | None = None) -> None`
- `verbose(self, message: str, context: str | None = None) -> None`
- `record(self, level: LogLevel, message: str, context: str | None = None, *, fields: Mapping[str, object] | None = None) -> None`
  Write one record at *level*, carrying *fields* as structured data.

This is the call that takes structured fields, rather than a keyword added to
each of the five level methods above. Those five are overridden by
applications and by this framework's own tests, and a parameter added to a
method someone else has already overridden turns their subclass into one that
no longer satisfies its base class - a breaking change bought for a keyword.

Field names are the caller's, and their values are redacted at every depth
against the configured keys before anything is written.
- `set_global_level(cls, level: LogLevel) -> None`
- `set_redacted_keys(cls, keys: frozenset[str] | set[str] | tuple[str, ...]) -> None`
  Replace the field names whose values are withheld from every record.
- `override_logger(cls, target: object) -> None`
  Send records to *target* for the context that calls this.

The binding is a context variable, so a second task that installs its own
override neither sees this one nor takes this one's records, and a task that
installs none keeps writing where it was writing before.
- `scoped_override(cls, target: object) -> Iterator[object]`
  Send records to *target* for the duration of the block.
- `reset_logger(cls) -> None`
  Undo the most recent override, and restore the default level and redaction.

#### `LoggerService`

```python
class LoggerService(Logger)
```

Defined in `bustan.observability.logger_service`.

Injectable wrapper around the framework logger.

#### `MetricsSink`

```python
class MetricsSink(Protocol)
```

Defined in `bustan.observability.observability`.

Metric sink used by the observability hooks.

One call per finished request, carrying the route labels, the status it was
answered with, and how long it took in seconds.

##### Methods

- `record_request(self, *, labels: Mapping[str, str], duration_seconds: float) -> None`

#### `Middleware`

```python
class Middleware
```

Defined in `bustan.pipeline.middleware`.

Base class for request middleware.

``use`` is given the request and a callable that continues the chain. Returning
what ``call_next`` returned passes the response through untouched; returning a
response of your own answers the request without the handler ever running. Both
the request and the response are the framework's own types, so a middleware is
written, and unit tested, without a web server anywhere in sight.

##### Methods

- `use(self, request: HttpRequest, call_next: CallNext) -> object`

#### `MiddlewareConsumer`

```python
class MiddlewareConsumer
```

Defined in `bustan.pipeline.middleware`.

Collect middleware bindings from module configuration callbacks.

##### Methods

- `apply(self, *middlewares: object) -> MiddlewareRegistration`

#### `ModuleRef`

```python
class ModuleRef
```

Defined in `bustan.addons.module_ref`.

Resolve providers through the finalized public application semantics.

##### Methods

- `(property) module_key`
  The module this reference resolves against.

A reference injected into a provider or a controller names the module that
class was declared in, so it sees exactly what the class's own constructor
sees. One asked of the application itself names the root module.
- `for_module(self, module: ModuleKey | type[object]) -> ModuleRef`
  Return a reference that resolves against another module of this application.
- `get(self, token: object, *, strict: bool = True) -> object`
  Resolve a provider, against the request being served when there is one.

This is the request-aware entry point: called from inside a handler, a guard or
an interceptor it reaches request-scoped providers and returns the same instance
the rest of that request sees. Called with no request in flight it resolves as
`ApplicationContext.get` does, and a request-scoped provider is refused.

`strict` keeps the lookup inside the module this reference names, which is the
module the class holding the reference was declared in. Pass `False` to widen a
token that module cannot see into a search of every module in the application,
so a provider another module declares privately is still reachable. The search
refuses to guess: a token more than one module declares raises rather than
picking one, and `for_module()` names the one to resolve through.
- `resolve(self, token: object, *, strict: bool = True) -> object`
  Alias for `get()`, with the same request-aware semantics.
- `create(self, cls: type[object]) -> object`
  Build one fresh instance of a class, against the request being served.

#### `Module`

```python
def Module(*, imports: Iterable[type[object] | DynamicModule] | None = None, controllers: Iterable[type[object]] | None = None, providers: Iterable[object | dict[str, Any]] | None = None, exports: Iterable[object] | None = None, is_global: bool = False) -> Callable[[ClassT], ClassT]
```

Defined in `bustan.kernel.module.decorators`.

Attach module metadata to a class without performing registration.

#### `ModuleGraph`

```python
class ModuleGraph
```

Defined in `bustan.kernel.module.graph`.

Validated view of the full module import graph.

##### Methods

- `get_node(self, key: ModuleKey) -> ModuleNode`
- `exports_for(self, key: ModuleKey) -> frozenset[object]`
- `controllers_for(self, key: ModuleKey) -> tuple[type[object], ...]`
- `available_providers_for(self, key: ModuleKey) -> frozenset[object]`
- `(property) root_module`
  Return the root module class.

#### `ModuleNode`

```python
class ModuleNode
```

Defined in `bustan.kernel.module.graph`.

Validated graph node for one decorated module instance.

##### Methods

- `(property) imports`
- `(property) controllers`
- `(property) providers`
  Return the token for each provider registered in this module.
- `(property) exports`

#### `ModuleCycleError`

```python
class ModuleCycleError(InvalidModuleError)
```

Defined in `bustan.kernel.errors`.

Raised when a module import cycle is detected.

#### `ObservabilityHooks`

```python
class ObservabilityHooks
```

Defined in `bustan.observability.observability`.

Route-aware metrics and tracing hooks around request execution.

##### Methods

- `current(cls) -> ObservabilityHooks`
- `resolve(cls, configured: ObservabilityHooks | None) -> ObservabilityHooks`
  Return the hooks one request is served under.

An override installed for the calling context wins, because that is what an
override is for: a test that redirects a request's metrics has to be able to
do so whatever the application it is testing was assembled with. Otherwise
the application serves under the hooks it was given, and an application given
none serves under hooks that record nothing rather than under no hooks at all.
- `override_global(cls, hooks: ObservabilityHooks) -> None`
- `scoped_override(cls, hooks: ObservabilityHooks) -> Iterator[ObservabilityHooks]`
- `reset_global(cls) -> None`
- `start_request(self, context: ExecutionContext) -> ActiveObservation`
  Begin observing one request, and start its server span when it is sampled.

An unsampled request is still measured and still counted; what head sampling
decides is whether a span is started for it, because the metric is what every
request costs and the span is what one request is worth keeping.
- `finish_request(self, observation: ActiveObservation, *, status_code: int, error: Exception | None = None) -> None`
  Close one request's observation, whatever it was answered with.

The duration is the elapsed time since the observation began, so it covers
everything the request paid for - the guards, the provider resolution, the
body, the handler and rendering the answer - and not merely the handler.

#### `OptionalDep`

```python
def OptionalDep() -> OptionalDependencyMarker
```

Defined in `bustan.common.decorators.injectable`.

Mark an ``Annotated`` dependency as optional without shadowing ``typing.Optional``.

#### `OnApplicationBootstrap`

```python
class OnApplicationBootstrap(Protocol)
```

Defined in `bustan.kernel.lifecycle.hooks`.

Protocol for components that run when the application starts.

##### Methods

- `on_application_bootstrap(self) -> None | Awaitable[None]`

#### `OnApplicationShutdown`

```python
class OnApplicationShutdown(Protocol)
```

Defined in `bustan.kernel.lifecycle.hooks`.

Protocol for components that run during application shutdown.

##### Methods

- `on_application_shutdown(self, signal: str | None) -> None | Awaitable[None]`

#### `OnModuleDestroy`

```python
class OnModuleDestroy(Protocol)
```

Defined in `bustan.kernel.lifecycle.hooks`.

Protocol for components that run when a module is torn down.

##### Methods

- `on_module_destroy(self) -> None | Awaitable[None]`

#### `OnModuleInit`

```python
class OnModuleInit(Protocol)
```

Defined in `bustan.kernel.lifecycle.hooks`.

Protocol for components that run during module initialization.

##### Methods

- `on_module_init(self) -> None | Awaitable[None]`

#### `Owner`

```python
def Owner(name: str) -> Callable[[DecoratedT], DecoratedT]
```

Defined in `bustan.security.policy`.

Record which team or person answers for this route.

``name`` is free text the framework only carries. Nothing in the request path reads
it; it reaches the route's compiled policy plan, and the governance ownership report
renders it from there, so a route can be traced to whoever maintains it without that
costing a request anything.

#### `Param`

Defined in `bustan.common.decorators.parameter`.

Makes a marker usable both bare (``Annotated[str, Body]``)
and as a call (``Annotated[str, Body("field")]``).

Current value: `Param`

#### `ParameterBindingError`

```python
class ParameterBindingError(BustanError)
```

Defined in `bustan.kernel.errors`.

Raised when request parameters cannot be bound.

##### Methods

- `to_payload(self) -> dict[str, str]`

#### `ParseArrayPipe`

```python
class ParseArrayPipe(Pipe)
```

Defined in `bustan.pipeline.built_in_pipes`.

Convert delimited strings into a list of strings.

##### Methods

- `transform(self, value: object, context: ExecutionContext) -> list[str]`
  Return the transformed parameter value passed to the handler.

#### `ParseBoolPipe`

```python
class ParseBoolPipe(Pipe)
```

Defined in `bustan.pipeline.built_in_pipes`.

Convert a parameter value into a boolean.

##### Methods

- `transform(self, value: object, context: ExecutionContext) -> bool`
  Return the transformed parameter value passed to the handler.

#### `ParseEnumPipe`

```python
class ParseEnumPipe(Pipe)
```

Defined in `bustan.pipeline.built_in_pipes`.

Resolve a raw value to an Enum member.

##### Methods

- `transform(self, value: object, context: ExecutionContext) -> Enum`
  Return the transformed parameter value passed to the handler.

#### `ParseFloatPipe`

```python
class ParseFloatPipe(Pipe)
```

Defined in `bustan.pipeline.built_in_pipes`.

Convert a parameter value into a float.

##### Methods

- `transform(self, value: object, context: ExecutionContext) -> float`
  Return the transformed parameter value passed to the handler.

#### `ParseIntPipe`

```python
class ParseIntPipe(Pipe)
```

Defined in `bustan.pipeline.built_in_pipes`.

Convert a parameter value into an integer.

##### Methods

- `transform(self, value: object, context: ExecutionContext) -> int`
  Return the transformed parameter value passed to the handler.

#### `ParseUUIDPipe`

```python
class ParseUUIDPipe(Pipe)
```

Defined in `bustan.pipeline.built_in_pipes`.

Convert a parameter value into a UUID instance.

##### Methods

- `transform(self, value: object, context: ExecutionContext) -> UUID`
  Return the transformed parameter value passed to the handler.

#### `Patch`

```python
def Patch(path: str = '/', *, version: str | list[str] | None = None, host: HostInput | None = None, hosts: HostInput | None = None) -> Callable[[FunctionT], FunctionT]
```

Defined in `bustan.common.decorators.route`.

Return a decorator that registers a PATCH route.

#### `Permissions`

```python
def Permissions(*permissions: str) -> Callable[[DecoratedT], DecoratedT]
```

Defined in `bustan.security.policy`.

Serve this route only to a caller holding every one of these permissions.

Read off the principal and accumulated across the controller and the handler
exactly as ``Roles`` are, and refused the same way. What separates the two is only
what an application chooses to put in each: the container never interprets either.

#### `Pipe`

```python
class Pipe
```

Defined in `bustan.pipeline.pipes`.

Base class for parameter transformation and validation.

##### Methods

- `transform(self, value: object, context: ExecutionContext) -> object | Awaitable[object]`
  Return the transformed parameter value passed to the handler.

#### `Post`

```python
def Post(path: str = '/', *, version: str | list[str] | None = None, host: HostInput | None = None, hosts: HostInput | None = None) -> Callable[[FunctionT], FunctionT]
```

Defined in `bustan.common.decorators.route`.

Return a decorator that registers a POST route.

#### `Principal`

```python
class Principal(Protocol)
```

Defined in `bustan.pipeline.auth`.

The caller a request is being served for: who they are, and what they may do.

#### `ProblemDetails`

```python
class ProblemDetails
```

Defined in `bustan.pipeline.filters`.

RFC 7807 problem details payload.

#### `ProblemDetailsExceptionFilter`

```python
class ProblemDetailsExceptionFilter(ExceptionFilter)
```

Defined in `bustan.pipeline.filters`.

Framework fallback filter that always emits problem-details responses.

##### Methods

- `catch(self, exc: Exception, context: ExecutionContext) -> HttpResponse`
  Convert an exception into a handler result or response payload.

#### `ProviderResolutionError`

```python
class ProviderResolutionError(BustanError)
```

Defined in `bustan.kernel.errors`.

Raised when dependency resolution fails.

#### `Public`

```python
def Public() -> Callable[[DecoratedT], DecoratedT]
```

Defined in `bustan.security.policy`.

Serve this route to anybody, whatever the controller around it requires.

Authentication and the role and permission checks are skipped, so nothing about
the caller is established and no principal reaches the handler. Written on a
handler it outranks the controller, which is what makes one open route on an
otherwise authenticated controller expressible; written beside an access
requirement at the same level it is contradictory and refused while the routes are
compiled. Guards the application registers itself still run: this waives the policy
these decorators declare, not every gate in front of the handler.

#### `Put`

```python
def Put(path: str = '/', *, version: str | list[str] | None = None, host: HostInput | None = None, hosts: HostInput | None = None) -> Callable[[FunctionT], FunctionT]
```

Defined in `bustan.common.decorators.route`.

Return a decorator that registers a PUT route.

#### `Query`

Defined in `bustan.common.decorators.parameter`.

Makes a marker usable both bare (``Annotated[str, Body]``)
and as a call (``Annotated[str, Body("field")]``).

Current value: `Query`

#### `RateLimit`

```python
def RateLimit(*, limit: int, window: str) -> Callable[[DecoratedT], DecoratedT]
```

Defined in `bustan.security.policy`.

Count this route's callers against a budget of its own, not the shared one.

``limit`` requests are allowed per ``window``, written as a whole number of seconds
or a whole number followed by ``s``, ``m``, ``h`` or ``d``. The route is counted
under a key of its own, so a request spends this budget instead of the
application-wide one rather than as well as it, and a caller over the limit is
refused with the headers that say how much is left and when to retry.

The counting is the throttler's. An application that has not installed throttling
records this policy and enforces nothing, so a route that must be bounded needs
both.

#### `ReadinessState`

```python
class ReadinessState
```

Defined in `bustan.health.readiness`.

Where this process is in its own lifetime, as far as routing traffic goes.

Two edges, and readiness is false outside the span between them.

**Started.** Set by the application bootstrap hook, which runs after every module
and provider has been initialized. Until then the process is alive but has not
finished assembling itself, and traffic sent to it would be served by an
application that is still being built.

**Draining.** Set when the process is asked to stop. Nothing in the lifecycle
records this on its own: a process that has been asked to stop is still fully
initialized and is still finishing the requests it already accepted, while it must
stop being sent new ones. Closing that gap is what this edge is for. The teardown
hook sets it as a backstop, so a shutdown nobody announced still withdraws the
process; a shutdown sequence that wants the process out of rotation *before* it
stops serving has to say so earlier, which is what ``begin_drain`` is for.

**The contract for whoever owns the shutdown sequence.** On a termination signal,
call ``begin_drain`` first, before the teardown hooks run and before any request is
refused, and only then wait for in-flight requests to finish. That order is the
whole point: readiness has to go false while the process is still serving normally,
so traffic is withdrawn from it by whatever routes traffic before it stops being
able to accept any. Draining only as part of teardown would take the process out of
rotation once it had already stopped serving, which is the outage this prevents.
An application that does not provide this state has no readiness probe either, so a
shutdown sequence that cannot resolve it has nothing to flip and drains without it.

Both edges are one-way within a lifecycle, and neither survives one: teardown drops
every instance the application built, so an application that is started again is
served by a new state that has neither edge set.

##### Methods

- `(property) started`
  Whether the application has finished starting up.
- `(property) draining`
  Whether this process has been asked to stop and wants no further traffic.
- `begin_drain(self) -> None`
  Record that the process is draining. Idempotent, and never reversed.
- `on_application_bootstrap(self) -> None`
  Record that startup reached the last stage the application runs.
- `before_application_shutdown(self, signal: str | None) -> None`
  Record that the process is going away, if nothing said so earlier.

#### `Reflector`

```python
class Reflector
```

Defined in `bustan.common.decorators.metadata`.

Read framework metadata with deterministic precedence rules.

##### Methods

- `create_decorator(name: str) -> MetadataDecorator[MetadataT]`
- `get(self, metadata: MetadataKey[MetadataT] | MetadataDecorator[MetadataT], target: object, *, inherit: bool = False) -> MetadataT | None`
- `get_all_and_override(self, metadata: MetadataKey[MetadataT] | MetadataDecorator[MetadataT], targets: Sequence[object], *, inherit: bool = False) -> MetadataT | None`
- `get_all_and_merge(self, metadata: MetadataKey[MetadataT] | MetadataDecorator[MetadataT], targets: Sequence[object], *, inherit: bool = False) -> tuple[MetadataT, ...]`

#### `REQUEST`

Defined in `bustan.kernel.ioc.tokens`.

A typed token representing a dependency for injection.

A token is its own identity: two tokens are the same token only when they are the
same object, so build each one once at module level and import it wherever it is
declared, injected or overridden. The name is what the token is called in errors;
the container never matches two tokens by comparing names.

Current value: `InjectionToken('REQUEST')`

#### `RESPONSE`

Defined in `bustan.kernel.ioc.tokens`.

A typed token representing a dependency for injection.

A token is its own identity: two tokens are the same token only when they are the
same object, so build each one once at module level and import it wherever it is
declared, injected or overridden. The name is what the token is called in errors;
the container never matches two tokens by comparing names.

Current value: `InjectionToken('RESPONSE')`

#### `RequestLimits`

```python
class RequestLimits
```

Defined in `bustan.runtime.params`.

What one application will spend on a single request.

``max_body_bytes`` bounds the body read to bind ordinary parameters and
``max_upload_bytes`` the body read to parse a multipart form; they are separate
because a route that accepts uploads is expected to carry more than a JSON
document, and giving both the larger bound would raise the ceiling on every route.
``max_upload_files`` bounds how many parts of a form may bind to one parameter.
``timeout_seconds`` is the wall clock one request may take before it is abandoned
and answered through the route's exception filters. ``sync_handler_threads`` is how
many synchronous handlers may run at once.

Every bound has a finite default. ``None`` removes one for a deployment that has
measured that it needs to, and is never what an application gets by not choosing.

A synchronous handler runs on a thread and Python cannot interrupt one, so
``timeout_seconds`` is enforced for such a handler only once it returns; what bounds
a synchronous handler that never returns is ``sync_handler_threads``, which caps how
many of them can be occupying threads at the same time.

#### `RequestTracer`

```python
class RequestTracer(Protocol)
```

Defined in `bustan.observability.observability`.

Tracer contract used by the runtime.

``context`` names the trace the span belongs to and the caller's span when the
request arrived inside a trace, so a span this process starts continues the
caller's trace rather than beginning one beside it.

##### Methods

- `start_span(self, name: str, *, kind: SpanKind, attributes: Mapping[str, str], context: SpanContext) -> TraceSpan`

#### `ResponseSerializer`

```python
class ResponseSerializer(Protocol)
```

Defined in `bustan.runtime.responses`.

Serializer contract used by the response handler.

##### Methods

- `serialize(self, value: object) -> HttpResponse | NativeHttpResponse`

#### `Roles`

```python
def Roles(*roles: str) -> Callable[[DecoratedT], DecoratedT]
```

Defined in `bustan.security.policy`.

Serve this route only to a caller holding every one of these roles.

The roles are read off the principal the route's authentication produced, and all
of them must be held: naming two means both, never either. Roles written on the
controller and on the handler add up rather than replace one another, so a handler
narrows what its controller requires and can never widen it. A caller carrying an
identity that lacks a role is refused as unable to retry, because presenting the
same identity again would change nothing; one carrying no identity is asked for one.

#### `RouteDefinitionError`

```python
class RouteDefinitionError(BustanError)
```

Defined in `bustan.kernel.errors`.

Raised when route metadata is malformed or duplicated.

#### `Scope`

```python
class Scope(StrEnum)
```

Defined in `bustan.common.types`.

Supported provider lifetimes.

#### `SpanContext`

```python
class SpanContext
```

Defined in `bustan.observability.observability`.

The identity of one span and the trace it belongs to.

``sampled`` is the head sampling decision, made once when the span starts and true
for the whole trace: a caller that sampled a request is honoured, and a request
that arrived without a decision gets one from the configured ratio.

#### `SpanKind`

```python
class SpanKind(StrEnum)
```

Defined in `bustan.observability.observability`.

Where a span sits in a call, in OpenTelemetry's terms.

#### `SpanStatus`

```python
class SpanStatus(StrEnum)
```

Defined in `bustan.observability.observability`.

The outcome a finished span reports.

#### `TraceSpan`

```python
class TraceSpan(Protocol)
```

Defined in `bustan.observability.observability`.

A span, in OpenTelemetry's terms: attributes, a status, and an end.

The runtime sets attributes while the request runs, records the exception when
there was one, sets the status once, and ends the span exactly once.

##### Methods

- `set_attribute(self, key: str, value: object) -> None`
- `set_status(self, status: SpanStatus, *, description: str | None = None) -> None`
- `record_exception(self, error: BaseException) -> None`
- `end(self) -> None`

#### `DefaultValuePipe`

```python
class DefaultValuePipe(Pipe)
```

Defined in `bustan.pipeline.built_in_pipes`.

Apply a default when the bound value is missing.

##### Methods

- `transform(self, value: object, context: ExecutionContext) -> object`
  Return the transformed parameter value passed to the handler.

#### `UploadedFile`

Defined in `bustan.common.decorators.parameter`.

Makes a marker usable both bare (``Annotated[str, Body]``)
and as a call (``Annotated[str, Body("field")]``).

Current value: `UploadedFile`

#### `UploadedFiles`

Defined in `bustan.common.decorators.parameter`.

Makes a marker usable both bare (``Annotated[str, Body]``)
and as a call (``Annotated[str, Body("field")]``).

Current value: `UploadedFiles`

#### `ValidationPipe`

```python
class ValidationPipe(Pipe)
```

Defined in `bustan.pipeline.built_in_pipes`.

Validate body payloads with Pydantic models when available.

##### Methods

- `transform(self, value: object, context: ExecutionContext) -> object`
  Return the transformed parameter value passed to the handler.

#### `application_context_id`

```python
def application_context_id(module: ModuleKey | type[object]) -> ContextId
```

Defined in `bustan.addons.context`.

No user-facing documentation provided.

#### `durable_context_id`

```python
def durable_context_id(provider: type[DurableProvider], request: HttpRequest | None) -> ContextId
```

Defined in `bustan.addons.context`.

No user-facing documentation provided.

#### `Ip`

Defined in `bustan.common.decorators.parameter`.

Makes a marker usable both bare (``Annotated[str, Body]``)
and as a call (``Annotated[str, Body("field")]``).

Current value: `Ip`

#### `request_context_id`

```python
def request_context_id(request: HttpRequest | None) -> ContextId
```

Defined in `bustan.addons.context`.

No user-facing documentation provided.

#### `VERSION_NEUTRAL`

str(object='') -> str
str(bytes_or_buffer[, encoding[, errors]]) -> str

Create a new string object from the given object. If encoding or
errors is specified, then the object must expose a data buffer
that will be decoded using the given encoding and error handler.
Otherwise, returns the result of object.__str__() (if defined)
or repr(object).
encoding defaults to 'utf-8'.
errors defaults to 'strict'.

Current value: `__VERSION_NEUTRAL__`

#### `VersioningOptions`

```python
class VersioningOptions
```

Defined in `bustan.runtime.versioning`.

VersioningOptions(type: 'VersioningType', prefix: 'str' = 'v', header: 'str' = 'X-API-Version', default_version: 'str | None' = None)

#### `VersioningType`

```python
class VersioningType(StrEnum)
```

Defined in `bustan.runtime.versioning`.

Enum where members are also (and must be) strings

#### `ConfigurableModuleBuilder`

```python
class ConfigurableModuleBuilder(Generic)
```

Defined in `bustan.kernel.module.builder`.

Build runtime-generated module classes with for_root-style helpers.

##### Methods

- `set_class_name(self, name: str) -> ConfigurableModuleBuilder[OptionsT]`
- `set_extras(self, *, providers: tuple[object | dict[str, object], ...] = ()) -> ConfigurableModuleBuilder[OptionsT]`
- `build(self) -> tuple[type[ConfigurableModuleDefinition[OptionsT]], InjectionToken[OptionsT]]`
  Return a generated module class and its stable options token.

#### `ConfigModule`

```python
class ConfigModule
```

Defined in `bustan.configuration.config_module`.

Factory helpers for configuration-backed dynamic modules.

##### Methods

- `for_root(*, env_file: str | list[str] | None = None, validation_schema: type | None = None, ignore_env_file: bool = False, is_global: bool = True) -> DynamicModule`

#### `ConfigService`

```python
class ConfigService
```

Defined in `bustan.configuration.config_service`.

Typed access to resolved configuration values.

##### Methods

- `get(self, key: str, default: Any = None) -> Any`
- `get_or_throw(self, key: str) -> Any`

#### `CorsOptions`

```python
class CorsOptions
```

Defined in `bustan.security.cors`.

Configuration for application-level CORS support.

#### `SkipThrottle`

```python
def SkipThrottle(handler)
```

Defined in `bustan.security.throttler`.

Mark a route handler as exempt from throttling.

#### `SwaggerModule`

```python
class SwaggerModule
```

Defined in `bustan.openapi.swagger_ui`.

Registers OpenAPI JSON and Swagger UI routes.

##### Methods

- `setup(app, path: str, document: dict[str, object], *, swagger_ui_path: str | None = None) -> None`

#### `SwaggerOptions`

```python
class SwaggerOptions
```

Defined in `bustan.openapi`.

SwaggerOptions(document_builder: 'DocumentBuilder', path: 'str' = '/api', swagger_ui_path: 'str | None' = None)

#### `ThrottleState`

```python
class ThrottleState
```

Defined in `bustan.security.throttler`.

What a throttling store knows about one key once it has counted a request.

``count`` is how many requests the key is answerable for inside the window, the
request just counted included. It exceeds the limit by exactly one when the request
was refused, because a refused request is not added to the window: refusing a caller
must not lengthen the wait it is already serving.

``reset_after`` is whole seconds until the oldest request still inside the window
leaves it, which is the moment ``count`` next falls. It is therefore also how long a
refused caller must wait before a request is accepted, and it is what the guard
sends as ``Retry-After``. It is ``0`` when the key has nothing counted against it,
and it never exceeds the window: a caller told to wait longer than the window it is
measured against has been told something that cannot be true.

#### `ThrottlerGuard`

```python
class ThrottlerGuard(Guard)
```

Defined in `bustan.security.throttler`.

Guard that rejects requests after the configured limit is exceeded.

##### Methods

- `can_activate(self, context: ExecutionContext) -> bool`
  Return True to allow request execution to continue.

#### `ThrottlerModule`

```python
class ThrottlerModule
```

Defined in `bustan.security.throttler`.

Factory for throttling support.

##### Methods

- `for_root(*, ttl: int, limit: int, key_resolver: ThrottlerKeyResolver | None = None, storage: ThrottlerStorage | None = None, trusted_proxies: Sequence[str] = (), max_keys: int = 10000) -> DynamicModule`
  Return a module that counts every request and refuses callers over the limit.

``ttl`` is the window in seconds and ``limit`` the requests one key may make
inside it. ``storage`` counts the requests; leave it unset for an in-process
store holding at most ``max_keys`` keys, and pass a shared implementation of
``ThrottlerStorage`` when the application runs as more than one worker, because
an in-process store counts each worker separately and N workers then allow N
times the limit.

``trusted_proxies`` is the list of addresses and CIDR blocks that are allowed to
name the caller on the application's behalf, given as the peers the application
accepts connections from. It is empty by default, which counts every request
under the address it arrived from and ignores forwarding headers entirely. Set
it to the load balancer the application actually sits behind, never to a wide
block: any peer in this list can put any address in ``X-Forwarded-For`` and be
counted as that caller, so listing a peer an attacker can connect from lets that
attacker spend another caller's allowance or evade its own limit.

``key_resolver`` replaces the derivation of the key altogether. A resolver of
your own is responsible for its own trust decisions, so ``trusted_proxies`` is
not consulted when one is given.

#### `ThrottlerStorage`

```python
class ThrottlerStorage(Protocol)
```

Defined in `bustan.security.throttler`.

Where the throttler keeps its per-key request windows.

Implement this to count requests somewhere every worker process can see, which is
what makes a configured limit mean the same thing behind a load balancer as it does
on one process: the in-process default counts each worker separately, so N workers
allow N times the limit. The method is asynchronous so an implementation backed by a
network service does not block the event loop while it waits.

An implementation must treat one call as one request: count it, and report the state
of the key afterwards. It must not add the request to the window when the window is
already full, so that a refused caller does not extend its own wait. Where several
processes share the store, counting and reporting have to happen as one atomic
operation, or two workers racing on the same key will both be told they are within
the limit.

##### Methods

- `count_request(self, key: str, ttl: int, limit: int) -> ThrottleState`

#### `UseFilters`

```python
def UseFilters(*filters: object) -> Callable[[DecoratedT], DecoratedT]
```

Defined in `bustan.pipeline.decorators`.

Attach one or more exception filters to a controller or handler.

#### `UseGuards`

```python
def UseGuards(*guards: object) -> Callable[[DecoratedT], DecoratedT]
```

Defined in `bustan.pipeline.decorators`.

Attach one or more guards to a controller or handler.

#### `UseInterceptors`

```python
def UseInterceptors(*interceptors: object) -> Callable[[DecoratedT], DecoratedT]
```

Defined in `bustan.pipeline.decorators`.

Attach one or more interceptors to a controller or handler.

#### `UsePipes`

```python
def UsePipes(*pipes: object) -> Callable[[DecoratedT], DecoratedT]
```

Defined in `bustan.pipeline.decorators`.

Attach one or more pipes to a controller or handler.

## `bustan.testing`

Supported testing helpers for the bustan package.

### Import

```python
from bustan.testing import create_test_app, create_test_module, override_provider
```

### Exports

#### `AsgiTestClient`

```python
class AsgiTestClient
```

Defined in `bustan.adapters.asgi.testclient`.

Drives one ASGI application in process, one request at a time.

Used as a context manager it runs the application's lifespan, so startup has
finished before the first request and shutdown runs after the last; used without
one, it sends requests to an application that was never started, which is what a
test that does not care about the lifespan wants.

Cookies a response set are kept and sent with later requests, so a test that logs in
and then asks for something stays logged in.

##### Methods

- `get(self, url: str, **options: Any) -> AsgiTestResponse`
  Send a GET request.
- `head(self, url: str, **options: Any) -> AsgiTestResponse`
  Send a HEAD request.
- `options(self, url: str, **options: Any) -> AsgiTestResponse`
  Send an OPTIONS request.
- `post(self, url: str, **options: Any) -> AsgiTestResponse`
  Send a POST request.
- `put(self, url: str, **options: Any) -> AsgiTestResponse`
  Send a PUT request.
- `patch(self, url: str, **options: Any) -> AsgiTestResponse`
  Send a PATCH request.
- `delete(self, url: str, **options: Any) -> AsgiTestResponse`
  Send a DELETE request.
- `request(self, method: str, url: str, *, params: Mapping[str, str] | None = None, headers: Mapping[str, str] | None = None, content: bytes | str | Iterable[bytes] | None = None, data: Mapping[str, str] | None = None, json: object | None = None, cookies: Mapping[str, str] | None = None, follow_redirects: bool = True) -> AsgiTestResponse`
  Send one request and return what the application answered.

The body is whichever of ``content``, ``data`` and ``json`` was supplied; the
last two also set the content type the application will parse them with. A
``content`` that is an iterable of chunks rather than one string of bytes is sent
the way a client streams a body it has not measured: the chunks arrive one
message at a time and the request declares no length, which is the only way to
reach the checks an application makes on a body it could not judge in advance.

#### `AsgiTestResponse`

```python
class AsgiTestResponse
```

Defined in `bustan.adapters.asgi.testclient`.

What one request to the application produced.

``status_code`` is the status the application started its response with,
``headers`` the headers it sent, ``content`` the body as raw bytes, and ``url``
the target the request finally landed on, which differs from the one asked for
when redirects were followed.

##### Methods

- `(property) text`
  The body decoded as UTF-8.
- `json(self) -> Any`
  The body decoded as JSON.

#### `CompiledTestingModule`

```python
class CompiledTestingModule
```

Defined in `bustan.testing.builder`.

Compiled application and container wrapper for tests.

##### Methods

- `(property) module_instances`
  The module instances the startup sequence built, keyed by module.
- `get(self, token: object) -> Any`
  Resolve a provider from the root module context.
- `resolve(self, token: object) -> Any`
  Alias for get().
- `snapshot_routes(self) -> tuple[dict[str, object], ...]`
  Return a deterministic snapshot of the compiled application routes.
- `diff_routes(self, previous_snapshot: Iterable[Mapping[str, object]]) -> tuple[dict[str, object], ...]`
  Compare a previous route snapshot against the current application routes.
- `create_client(self) -> AsgiTestClient`
  Return an in-process client that sends requests to the compiled application.

The client is the framework's own, so a test needs no HTTP client package
beyond what the application already installs. Used as a context manager it
runs the application's ASGI lifespan; a compiled module has already started
through its lifecycle manager, so entering it changes nothing that startup
did and leaving it is not a substitute for close().
- `close(self) -> None`
  Tear the compiled application down through its own lifecycle.

Teardown belongs to the application's lifecycle manager, so the stages run in
the order a served application runs them, a second call does nothing, and
every failing hook is reported rather than only the first one.

#### `PipelineOverrideRegistry`

```python
class PipelineOverrideRegistry
```

Defined in `bustan.testing.overrides`.

Stores replacements for pipeline classes in test contexts.

##### Methods

- `apply_to_metadata(self, metadata: PipelineMetadata) -> PipelineMetadata`
  Return metadata with known pipeline components replaced.

#### `TestingModuleBuilder`

```python
class TestingModuleBuilder
```

Defined in `bustan.testing.builder`.

Fluent builder for testing applications and container overrides.

##### Methods

- `override_provider(self, token: object) -> _ProviderOverrideChain`
  Begin replacing the provider bound to a token.
- `override_guard(self, original: object) -> _PipelineOverrideChain`
  Begin replacing a guard class wherever the application declares it.
- `override_pipe(self, original: object) -> _PipelineOverrideChain`
  Begin replacing a pipe class wherever the application declares it.
- `override_interceptor(self, original: object) -> _PipelineOverrideChain`
  Begin replacing an interceptor class wherever the application declares it.
- `override_filter(self, original: object) -> _PipelineOverrideChain`
  Begin replacing a filter class wherever the application declares it.
- `compile(self) -> CompiledTestingModule`
  Build the application, apply every override, and run its startup sequence.

Startup is the application's own, so a graph a served application can start is
a graph a test can start: async singleton factories are warmed before any hook
runs, and the lifecycle manager knows afterwards that startup has happened.

#### `create_test_app`

```python
def create_test_app(root_module: type[object], *, provider_overrides: Mapping[object, object] | None = None) -> Application
```

Defined in `bustan.testing.builder`.

Create an application and apply any requested provider overrides.

#### `create_test_module`

```python
def create_test_module(*, name: str = 'TestModule', imports: Iterable[type[object]] | None = None, controllers: Iterable[type[object]] | None = None, providers: Iterable[type[object] | dict[str, object]] | None = None, exports: Iterable[object] | None = None) -> type[object]
```

Defined in `bustan.testing.builder`.

Create a throwaway decorated module for isolated tests.

#### `create_testing_module`

```python
def create_testing_module(root_module: type[object]) -> TestingModuleBuilder
```

Defined in `bustan.testing.builder`.

Create a testing-module builder for the supplied root module.

#### `override_provider`

```python
def override_provider(target: object, token: object, replacement: object, *, module_cls: type[object] | None = None) -> Iterator[None]
```

Defined in `bustan.testing.overrides`.

Temporarily replace a provider, before the application it belongs to starts.

``target`` is the container to override in, the ``Application`` holding it, or the
server object it was assembled with, which carries the container on its own state
namespace. Anything else raises ``TypeError``.

An override belongs to bootstrap. It does not stand beside the provider it
replaces for the length of the block; it replaces it for the whole application,
including every instance already built from it. Against an application that has
started, that is refused rather than half honoured: the singletons startup built
from the real provider are the ones still being served, so a block that appeared
to swap a dependency would have swapped nothing. Assemble the application with the
replacement instead, with
``await create_testing_module(RootModule).override_provider(token).use_value(...).compile()``.

## `bustan.errors`

Re-export of bustan errors for backward compatibility.

### Import

```python
from bustan.errors import ProviderResolutionError, RouteDefinitionError, BustanError
```

### Exports

#### `AuthenticationRequiredError`

```python
class AuthenticationRequiredError(GuardRejectedError)
```

Defined in `bustan.kernel.errors`.

Raised when a route needs an authenticated caller and the request has none.

It refuses exactly the requests a guard already refused; it says only that the
refusal was for want of an identity rather than for want of a permission, which is
what separates a 401 the caller can retry after authenticating from a 403 it cannot.

#### `AuthenticatorRegistryError`

```python
class AuthenticatorRegistryError(BustanError)
```

Defined in `bustan.kernel.errors`.

Raised when the authenticator wiring a route needs is missing or unusable.

A route that authenticates its callers reads its authenticators out of a registry
bound under ``AUTHENTICATOR_REGISTRY``. A registry no module visible to the route
provides, or one that cannot be built without awaiting it, cannot authenticate
anybody, so every caller of that route would be refused however good its
credentials. That is a mistake in the application rather than in the request, so it
is raised while the application is being built, and separately from the errors that
report a refused caller.

#### `BadGatewayException`

```python
class BadGatewayException(HttpException)
```

Defined in `bustan.kernel.errors`.

Raise to answer 502 when a service this one depends on answered unusably.

#### `ConflictException`

```python
class ConflictException(HttpException)
```

Defined in `bustan.kernel.errors`.

Raise to answer 409 when the request contradicts the resource's current state.

#### `ContentTooLargeException`

```python
class ContentTooLargeException(HttpException)
```

Defined in `bustan.kernel.errors`.

Raise to answer 413 when the request body is larger than the route accepts.

#### `ExportViolationError`

```python
class ExportViolationError(InvalidModuleError)
```

Defined in `bustan.kernel.errors`.

Raised when a module exports a provider it does not declare.

#### `ForbiddenException`

```python
class ForbiddenException(HttpException)
```

Defined in `bustan.kernel.errors`.

Raise to answer 403 when an identified caller is not allowed to do this.

Say what is refused, never why in terms of the application's own roles or
permissions: the caller being refused is the one party those names must not reach.

#### `GatewayTimeoutException`

```python
class GatewayTimeoutException(HttpException)
```

Defined in `bustan.kernel.errors`.

Raise to answer 504 when a service this one depends on did not answer in time.

#### `GuardRejectedError`

```python
class GuardRejectedError(BustanError)
```

Defined in `bustan.kernel.errors`.

Raised when a guard blocks request execution.

#### `HttpException`

```python
class HttpException(BustanError)
```

Defined in `bustan.kernel.errors`.

Base class for an exception that names the response its caller receives.

Raise one of its subclasses from a handler, a pipe, an interceptor or a filter to
answer the caller with a status the route would not otherwise return. Each subclass
fixes the status, the problem type and the code the response carries, so the same
condition is always reported the same way, and the message passed in is returned to
the caller as the problem's ``detail``.

A message given to a subclass whose status is 500 or above is not shown to the
caller. Those statuses report a fault in the application rather than anything the
caller can act on, and their messages routinely name internal detail, so the status
reason is returned in place of the message and the message is kept in the log.

``headers`` adds response headers the status needs, such as the challenge a 401
carries. Passing a header the subclass also sets by default replaces that default.

#### `InternalServerErrorException`

```python
class InternalServerErrorException(HttpException)
```

Defined in `bustan.kernel.errors`.

Raise to answer 500 when the application cannot serve the request.

The message reaches the log and not the caller, so write it for whoever is on call.

#### `InvalidControllerError`

```python
class InvalidControllerError(BustanError)
```

Defined in `bustan.kernel.errors`.

Raised when a controller declaration is invalid.

#### `InvalidModuleError`

```python
class InvalidModuleError(BustanError)
```

Defined in `bustan.kernel.errors`.

Raised when module declarations or imports are invalid.

#### `InvalidPipelineError`

```python
class InvalidPipelineError(BustanError)
```

Defined in `bustan.kernel.errors`.

Raised when pipeline decorators or components are invalid.

#### `InvalidProviderError`

```python
class InvalidProviderError(BustanError)
```

Defined in `bustan.kernel.errors`.

Raised when a provider declaration is invalid.

#### `LifecycleError`

```python
class LifecycleError(BustanError)
```

Defined in `bustan.kernel.errors`.

Raised when application lifecycle hooks fail.

#### `MethodNotAllowedException`

```python
class MethodNotAllowedException(HttpException)
```

Defined in `bustan.kernel.errors`.

Raise to answer 405 when the resource exists but not for this method.

#### `ModuleCycleError`

```python
class ModuleCycleError(InvalidModuleError)
```

Defined in `bustan.kernel.errors`.

Raised when a module import cycle is detected.

#### `NotFoundException`

```python
class NotFoundException(HttpException)
```

Defined in `bustan.kernel.errors`.

Raise to answer 404 when the addressed resource does not exist.

#### `NotImplementedException`

```python
class NotImplementedException(HttpException)
```

Defined in `bustan.kernel.errors`.

Raise to answer 501 when the route exists but the behaviour is not written yet.

#### `BadRequestException`

```python
class BadRequestException(HttpException)
```

Defined in `bustan.kernel.errors`.

Raised when a request fails explicit validation.

The message reaches the caller, because it is about the request that was just
sent: which field was wrong, where it was read from and what was expected there.

##### Methods

- `to_payload(self) -> dict[str, str]`

#### `ParameterBindingError`

```python
class ParameterBindingError(BustanError)
```

Defined in `bustan.kernel.errors`.

Raised when request parameters cannot be bound.

##### Methods

- `to_payload(self) -> dict[str, str]`

#### `ProviderResolutionError`

```python
class ProviderResolutionError(BustanError)
```

Defined in `bustan.kernel.errors`.

Raised when dependency resolution fails.

#### `RequestBodyTooLargeError`

```python
class RequestBodyTooLargeError(BustanError)
```

Defined in `bustan.runtime.params`.

Raised when a request carries more body bytes or parts than the limit allows.

#### `RequestTimeoutError`

```python
class RequestTimeoutError(BustanError)
```

Defined in `bustan.runtime.execution`.

Raised when one request took longer than the time its application allows it.

#### `RouteDefinitionError`

```python
class RouteDefinitionError(BustanError)
```

Defined in `bustan.kernel.errors`.

Raised when route metadata is malformed or duplicated.

#### `ServiceUnavailableException`

```python
class ServiceUnavailableException(HttpException)
```

Defined in `bustan.kernel.errors`.

Raise to answer 503 when the application is up but cannot serve requests now.

#### `TooManyRequestsException`

```python
class TooManyRequestsException(HttpException)
```

Defined in `bustan.kernel.errors`.

Raise to answer 429 when the caller has exceeded a rate it is held to.

#### `UnauthorizedException`

```python
class UnauthorizedException(HttpException)
```

Defined in `bustan.kernel.errors`.

Raise to answer 401 when the request carries no usable credentials.

The response carries a ``WWW-Authenticate`` challenge, because a 401 without one
tells a client it must authenticate without telling it how. The default names the
bearer scheme; pass ``headers`` to state the scheme the application really uses.

Use this when the caller is unknown. A caller the application has identified and is
refusing anyway is answered with :class:`ForbiddenException`.

#### `UnprocessableEntityException`

```python
class UnprocessableEntityException(HttpException)
```

Defined in `bustan.kernel.errors`.

Raise to answer 422 when a well-formed body asks for something impossible.

A body the framework could not read at all is a 400 the caller is told about
through :class:`BadRequestException`; this status is for one that parsed and then
failed a rule the application enforces.

#### `UnsupportedMediaTypeException`

```python
class UnsupportedMediaTypeException(HttpException)
```

Defined in `bustan.kernel.errors`.

Raise to answer 415 when the body is in a format the handler cannot read.

#### `BustanError`

```python
class BustanError(Exception)
```

Defined in `bustan.kernel.errors`.

Base exception for the framework.
