# API Reference

This document is generated from docstrings in the stable public modules.
Regenerate it with `uv run python scripts/generate_api_reference.py`.

Stable modules:
- `bustan`
- `bustan.testing`
- `bustan.errors`

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
- `enable_cors(self, options: CorsOptions | None = None) -> None`
  Register Starlette's CORS middleware on the application.
- `enable_swagger(self, path: str, document: dict[str, object], *, swagger_ui_path: str | None = None) -> None`
  Register OpenAPI JSON and Swagger UI routes.
- `listen(self, port: int, host: str = '127.0.0.1', reload: bool = False, **kwargs: Any) -> None`
  Start the ASGI server asynchronously via the adapter.
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
- `get(self, token: object) -> Any`
  Resolve a provider from the root module context.

This is a non-request-scoped resolution. For request-scoped
providers, use the dependency injection system directly via
decorators (@Param, @Body, etc.) or app.resolve().
- `resolve(self, token: object) -> Any`
  Alias for app.get().
- `close(self) -> None`
  Trigger the application shutdown sequence.

Mainly used for graceful teardown in tests.

#### `APP_FILTER`

Defined in `bustan.core.ioc.tokens`.

A typed token representing a dependency for injection.

Current value: `InjectionToken('APP_FILTER')`

#### `APP_GUARD`

Defined in `bustan.core.ioc.tokens`.

A typed token representing a dependency for injection.

Current value: `InjectionToken('APP_GUARD')`

#### `APP_INTERCEPTOR`

Defined in `bustan.core.ioc.tokens`.

A typed token representing a dependency for injection.

Current value: `InjectionToken('APP_INTERCEPTOR')`

#### `APP_PIPE`

Defined in `bustan.core.ioc.tokens`.

A typed token representing a dependency for injection.

Current value: `InjectionToken('APP_PIPE')`

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

#### `BadRequestException`

```python
class BadRequestException(BustanError)
```

Defined in `bustan.core.errors`.

Raised when a request fails explicit validation.

#### `Body`

Defined in `bustan.common.decorators.parameter`.

Makes a marker usable both bare (``Annotated[str, Body]``)
and as a call (``Annotated[str, Body("field")]``).

Current value: `Body`

#### `Cookies`

Defined in `bustan.common.decorators.parameter`.

Makes a marker usable both bare (``Annotated[str, Body]``)
and as a call (``Annotated[str, Body("field")]``).

Current value: `Cookies`

#### `create_app`

```python
def create_app(root_module: type[object] | DynamicModule, *, debug: bool = False, adapter: AbstractHttpAdapter | None = None, pipeline_override_registry: PipelineOverrideRegistry | None = None, versioning: VersioningOptions | None = None, swagger: SwaggerOptions | None = None) -> Application
```

Defined in `bustan.app.bootstrap`.

Create a fully assembled Bustan application from the root module.

#### `create_app_context`

```python
def create_app_context(root_module: type[object] | DynamicModule) -> ApplicationContext
```

Defined in `bustan.app.bootstrap`.

Create a standalone application context for dependency injection.

#### `BustanError`

```python
class BustanError(Exception)
```

Defined in `bustan.core.errors`.

Base exception for the framework.

#### `Controller`

```python
def Controller(prefix: str = '', *, scope: ProviderScope | str = ProviderScope.SINGLETON, version: str | list[str] | None = None) -> Callable[[ClassT], ClassT]
```

Defined in `bustan.common.decorators.controller`.

Attach controller metadata to a class.

#### `Delete`

```python
def Delete(path: str = '/', *, version: str | list[str] | None = None) -> Callable[[FunctionT], FunctionT]
```

Defined in `bustan.common.decorators.route`.

Return a decorator that registers a DELETE route.

#### `DurableProvider`

```python
class DurableProvider(Protocol)
```

Defined in `bustan.core.ioc.scopes`.

Protocol for providers that derive a durable cache key from the request.

##### Methods

- `get_durable_context_key(cls, request: Request | None) -> Hashable`

#### `DynamicModule`

```python
class DynamicModule
```

Defined in `bustan.core.module.dynamic`.

Metadata overlay that compiles into a unique module instance.

#### `DocumentBuilder`

```python
class DocumentBuilder
```

Defined in `bustan.openapi.document_builder`.

Fluent builder for the base OpenAPI document.

##### Methods

- `set_title(self, title: str) -> 'DocumentBuilder'`
- `set_version(self, version: str) -> 'DocumentBuilder'`
- `set_description(self, description: str) -> 'DocumentBuilder'`
- `add_bearer_auth(self, name: str = 'bearer') -> 'DocumentBuilder'`
- `build(self) -> dict[str, object]`

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

- `catch(self, exc: Exception, context: RequestContext) -> object`
  Convert an exception into a handler result or response payload.

#### `ExportViolationError`

```python
class ExportViolationError(InvalidModuleError)
```

Defined in `bustan.core.errors`.

Raised when a module exports a provider it does not declare.

#### `Get`

```python
def Get(path: str = '/', *, version: str | list[str] | None = None) -> Callable[[FunctionT], FunctionT]
```

Defined in `bustan.common.decorators.route`.

Return a decorator that registers a GET route.

#### `Guard`

```python
class Guard
```

Defined in `bustan.pipeline.guards`.

Base class for authorization and policy gates.

##### Methods

- `can_activate(self, context: RequestContext) -> bool`
  Return True to allow request execution to continue.

#### `GuardRejectedError`

```python
class GuardRejectedError(BustanError)
```

Defined in `bustan.core.errors`.

Raised when a guard blocks request execution.

#### `Header`

Defined in `bustan.common.decorators.parameter`.

Makes a marker usable both bare (``Annotated[str, Body]``)
and as a call (``Annotated[str, Body("field")]``).

Current value: `Header`

#### `HostParam`

Defined in `bustan.common.decorators.parameter`.

Makes a marker usable both bare (``Annotated[str, Body]``)
and as a call (``Annotated[str, Body("field")]``).

Current value: `HostParam`

#### `Injectable`

```python
def Injectable(target: ClassT | None = None, *, scope: ProviderScope | str = ProviderScope.SINGLETON) -> ClassT | Callable[[ClassT], ClassT]
```

Defined in `bustan.common.decorators.injectable`.

Mark a class as a DI-managed provider with the selected scope.

#### `InjectionToken`

```python
class InjectionToken(Generic)
```

Defined in `bustan.core.ioc.tokens`.

A typed token representing a dependency for injection.

#### `Interceptor`

```python
class Interceptor
```

Defined in `bustan.pipeline.interceptors`.

Base class for around-handler behaviors.

##### Methods

- `intercept(self, context: HandlerContext, call_next: CallNext) -> object`
  Wrap handler execution and optionally transform the result.

#### `InvalidControllerError`

```python
class InvalidControllerError(BustanError)
```

Defined in `bustan.core.errors`.

Raised when a controller declaration is invalid.

#### `InvalidModuleError`

```python
class InvalidModuleError(BustanError)
```

Defined in `bustan.core.errors`.

Raised when module declarations or imports are invalid.

#### `InvalidPipelineError`

```python
class InvalidPipelineError(BustanError)
```

Defined in `bustan.core.errors`.

Raised when pipeline decorators or components are invalid.

#### `InvalidProviderError`

```python
class InvalidProviderError(BustanError)
```

Defined in `bustan.core.errors`.

Raised when a provider declaration is invalid.

#### `LifecycleError`

```python
class LifecycleError(BustanError)
```

Defined in `bustan.core.errors`.

Raised when application lifecycle hooks fail.

#### `LogLevel`

```python
class LogLevel(IntEnum)
```

Defined in `bustan.logger.logger`.

Enum where members are also (and must be) ints

#### `Logger`

```python
class Logger
```

Defined in `bustan.logger.logger`.

NestJS-style logger with context labels and level filtering.

##### Methods

- `log(self, message: str, context: str | None = None) -> None`
- `warn(self, message: str, context: str | None = None) -> None`
- `error(self, message: str, trace: str | None = None, context: str | None = None) -> None`
- `debug(self, message: str, context: str | None = None) -> None`
- `verbose(self, message: str, context: str | None = None) -> None`
- `set_global_level(cls, level: LogLevel) -> None`
- `override_logger(cls, target: object) -> None`
- `reset_logger(cls) -> None`

#### `LoggerService`

```python
class LoggerService(Logger)
```

Defined in `bustan.logger.logger_service`.

Injectable wrapper around the framework logger.

#### `Middleware`

```python
class Middleware
```

Defined in `bustan.pipeline.middleware`.

Base class for request middleware.

##### Methods

- `use(self, request: Request, call_next: CallNext) -> Response`

#### `MiddlewareConsumer`

```python
class MiddlewareConsumer
```

Defined in `bustan.pipeline.middleware`.

Collect middleware bindings from module configuration callbacks.

##### Methods

- `apply(self, *middlewares: object) -> MiddlewareRegistration`

#### `Module`

```python
def Module(*, imports: Iterable[type[object] | DynamicModule] | None = None, controllers: Iterable[type[object]] | None = None, providers: Iterable[object | dict[str, Any]] | None = None, exports: Iterable[object] | None = None, is_global: bool = False) -> Callable[[ClassT], ClassT]
```

Defined in `bustan.core.module.decorators`.

Attach module metadata to a class without performing registration.

#### `ModuleCycleError`

```python
class ModuleCycleError(InvalidModuleError)
```

Defined in `bustan.core.errors`.

Raised when a module import cycle is detected.

#### `OnApplicationBootstrap`

```python
class OnApplicationBootstrap(Protocol)
```

Defined in `bustan.core.lifecycle.hooks`.

Protocol for components that run when the application starts.

##### Methods

- `on_app_startup(self) -> None | Awaitable[None]`

#### `OnApplicationShutdown`

```python
class OnApplicationShutdown(Protocol)
```

Defined in `bustan.core.lifecycle.hooks`.

Protocol for components that run during application shutdown.

##### Methods

- `on_app_shutdown(self) -> None | Awaitable[None]`

#### `OnModuleDestroy`

```python
class OnModuleDestroy(Protocol)
```

Defined in `bustan.core.lifecycle.hooks`.

Protocol for components that run when a module is torn down.

##### Methods

- `on_module_destroy(self) -> None | Awaitable[None]`

#### `OnModuleInit`

```python
class OnModuleInit(Protocol)
```

Defined in `bustan.core.lifecycle.hooks`.

Protocol for components that run during module initialization.

##### Methods

- `on_module_init(self) -> None | Awaitable[None]`

#### `Param`

Defined in `bustan.common.decorators.parameter`.

Makes a marker usable both bare (``Annotated[str, Body]``)
and as a call (``Annotated[str, Body("field")]``).

Current value: `Param`

#### `ParameterBindingError`

```python
class ParameterBindingError(BustanError)
```

Defined in `bustan.core.errors`.

Raised when request parameters cannot be bound.

#### `ParseArrayPipe`

```python
class ParseArrayPipe(Pipe)
```

Defined in `bustan.pipeline.built_in_pipes`.

Convert delimited strings into a list of strings.

##### Methods

- `transform(self, value: object, context: ParameterContext) -> list[str]`
  Return the transformed parameter value passed to the handler.

#### `ParseBoolPipe`

```python
class ParseBoolPipe(Pipe)
```

Defined in `bustan.pipeline.built_in_pipes`.

Convert a parameter value into a boolean.

##### Methods

- `transform(self, value: object, context: ParameterContext) -> bool`
  Return the transformed parameter value passed to the handler.

#### `ParseEnumPipe`

```python
class ParseEnumPipe(Pipe)
```

Defined in `bustan.pipeline.built_in_pipes`.

Resolve a raw value to an Enum member.

##### Methods

- `transform(self, value: object, context: ParameterContext) -> Enum`
  Return the transformed parameter value passed to the handler.

#### `ParseFloatPipe`

```python
class ParseFloatPipe(Pipe)
```

Defined in `bustan.pipeline.built_in_pipes`.

Convert a parameter value into a float.

##### Methods

- `transform(self, value: object, context: ParameterContext) -> float`
  Return the transformed parameter value passed to the handler.

#### `ParseIntPipe`

```python
class ParseIntPipe(Pipe)
```

Defined in `bustan.pipeline.built_in_pipes`.

Convert a parameter value into an integer.

##### Methods

- `transform(self, value: object, context: ParameterContext) -> int`
  Return the transformed parameter value passed to the handler.

#### `ParseUUIDPipe`

```python
class ParseUUIDPipe(Pipe)
```

Defined in `bustan.pipeline.built_in_pipes`.

Convert a parameter value into a UUID instance.

##### Methods

- `transform(self, value: object, context: ParameterContext) -> UUID`
  Return the transformed parameter value passed to the handler.

#### `Patch`

```python
def Patch(path: str = '/', *, version: str | list[str] | None = None) -> Callable[[FunctionT], FunctionT]
```

Defined in `bustan.common.decorators.route`.

Return a decorator that registers a PATCH route.

#### `Pipe`

```python
class Pipe
```

Defined in `bustan.pipeline.pipes`.

Base class for parameter transformation and validation.

##### Methods

- `transform(self, value: object, context: ParameterContext) -> object`
  Return the transformed parameter value passed to the handler.

#### `Post`

```python
def Post(path: str = '/', *, version: str | list[str] | None = None) -> Callable[[FunctionT], FunctionT]
```

Defined in `bustan.common.decorators.route`.

Return a decorator that registers a POST route.

#### `ProviderResolutionError`

```python
class ProviderResolutionError(BustanError)
```

Defined in `bustan.core.errors`.

Raised when dependency resolution fails.

#### `Put`

```python
def Put(path: str = '/', *, version: str | list[str] | None = None) -> Callable[[FunctionT], FunctionT]
```

Defined in `bustan.common.decorators.route`.

Return a decorator that registers a PUT route.

#### `Query`

Defined in `bustan.common.decorators.parameter`.

Makes a marker usable both bare (``Annotated[str, Body]``)
and as a call (``Annotated[str, Body("field")]``).

Current value: `Query`

#### `RouteDefinitionError`

```python
class RouteDefinitionError(BustanError)
```

Defined in `bustan.core.errors`.

Raised when route metadata is malformed or duplicated.

#### `Scope`

```python
class Scope(StrEnum)
```

Defined in `bustan.common.types`.

Supported provider lifetimes.

#### `DefaultValuePipe`

```python
class DefaultValuePipe(Pipe)
```

Defined in `bustan.pipeline.built_in_pipes`.

Apply a default when the bound value is missing.

##### Methods

- `transform(self, value: object, context: ParameterContext) -> object`
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

- `transform(self, value: object, context: ParameterContext) -> object`
  Return the transformed parameter value passed to the handler.

#### `Ip`

Defined in `bustan.common.decorators.parameter`.

Makes a marker usable both bare (``Annotated[str, Body]``)
and as a call (``Annotated[str, Body("field")]``).

Current value: `Ip`

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

Defined in `bustan.platform.http.versioning`.

VersioningOptions(type: 'VersioningType', prefix: 'str' = 'v', header: 'str' = 'X-API-Version', default_version: 'str | None' = None)

#### `VersioningType`

```python
class VersioningType(StrEnum)
```

Defined in `bustan.platform.http.versioning`.

Enum where members are also (and must be) strings

#### `ConfigurableModuleBuilder`

```python
class ConfigurableModuleBuilder(Generic)
```

Defined in `bustan.core.module.builder`.

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

Defined in `bustan.config.config_module`.

Factory helpers for configuration-backed dynamic modules.

##### Methods

- `for_root(*, env_file: str | list[str] | None = None, validation_schema: type | None = None, ignore_env_file: bool = False, is_global: bool = True) -> DynamicModule`

#### `ConfigService`

```python
class ConfigService
```

Defined in `bustan.config.config_service`.

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

#### `ThrottlerGuard`

```python
class ThrottlerGuard(Guard)
```

Defined in `bustan.security.throttler`.

Guard that rejects requests after the configured limit is exceeded.

##### Methods

- `can_activate(self, context: RequestContext) -> bool`
  Return True to allow request execution to continue.

#### `ThrottlerModule`

```python
class ThrottlerModule
```

Defined in `bustan.security.throttler`.

Factory for throttling support.

##### Methods

- `for_root(*, ttl: int, limit: int) -> DynamicModule`

#### `ThrottlerStorage`

```python
class ThrottlerStorage(Protocol)
```

Defined in `bustan.security.throttler`.

Protocol for request counting backends.

##### Methods

- `increment(self, key: str, ttl: int) -> int`
- `get_ttl(self, key: str) -> int`

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

#### `CompiledTestingModule`

```python
class CompiledTestingModule
```

Defined in `bustan.testing.builder`.

Compiled application and container wrapper for tests.

##### Methods

- `get(self, token: object) -> Any`
- `resolve(self, token: object) -> Any`
- `close(self) -> None`

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
- `override_guard(self, original: object) -> _PipelineOverrideChain`
- `override_pipe(self, original: object) -> _PipelineOverrideChain`
- `override_interceptor(self, original: object) -> _PipelineOverrideChain`
- `override_filter(self, original: object) -> _PipelineOverrideChain`
- `compile(self) -> CompiledTestingModule`

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
def override_provider(target: Starlette | Application | Container, token: object, replacement: object, *, module_cls: type[object] | None = None) -> Iterator[None]
```

Defined in `bustan.testing.overrides`.

Temporarily replace a provider for the duration of a context block.

## `bustan.errors`

Re-export of bustan errors for backward compatibility.

### Import

```python
from bustan.errors import ProviderResolutionError, RouteDefinitionError, BustanError
```

### Exports

#### `ExportViolationError`

```python
class ExportViolationError(InvalidModuleError)
```

Defined in `bustan.core.errors`.

Raised when a module exports a provider it does not declare.

#### `GuardRejectedError`

```python
class GuardRejectedError(BustanError)
```

Defined in `bustan.core.errors`.

Raised when a guard blocks request execution.

#### `InvalidControllerError`

```python
class InvalidControllerError(BustanError)
```

Defined in `bustan.core.errors`.

Raised when a controller declaration is invalid.

#### `InvalidModuleError`

```python
class InvalidModuleError(BustanError)
```

Defined in `bustan.core.errors`.

Raised when module declarations or imports are invalid.

#### `InvalidPipelineError`

```python
class InvalidPipelineError(BustanError)
```

Defined in `bustan.core.errors`.

Raised when pipeline decorators or components are invalid.

#### `InvalidProviderError`

```python
class InvalidProviderError(BustanError)
```

Defined in `bustan.core.errors`.

Raised when a provider declaration is invalid.

#### `LifecycleError`

```python
class LifecycleError(BustanError)
```

Defined in `bustan.core.errors`.

Raised when application lifecycle hooks fail.

#### `ModuleCycleError`

```python
class ModuleCycleError(InvalidModuleError)
```

Defined in `bustan.core.errors`.

Raised when a module import cycle is detected.

#### `BadRequestException`

```python
class BadRequestException(BustanError)
```

Defined in `bustan.core.errors`.

Raised when a request fails explicit validation.

#### `ParameterBindingError`

```python
class ParameterBindingError(BustanError)
```

Defined in `bustan.core.errors`.

Raised when request parameters cannot be bound.

#### `ProviderResolutionError`

```python
class ProviderResolutionError(BustanError)
```

Defined in `bustan.core.errors`.

Raised when dependency resolution fails.

#### `RouteDefinitionError`

```python
class RouteDefinitionError(BustanError)
```

Defined in `bustan.core.errors`.

Raised when route metadata is malformed or duplicated.

#### `BustanError`

```python
class BustanError(Exception)
```

Defined in `bustan.core.errors`.

Base exception for the framework.
