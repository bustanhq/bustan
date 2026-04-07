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
- `listen(self, port: int, host: str = '127.0.0.1', reload: bool = False, **kwargs: Any) -> None`
  Start the ASGI server asynchronously via the adapter.

#### `ApplicationContext`

```python
class ApplicationContext
```

Defined in `bustan.app.application`.

A standalone application context for dependency injection.

This provides a clean interface for resolving services from the Bustan
IoC container, without an associated HTTP server instance.

##### Methods

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

#### `Body`

Defined in `bustan.common.decorators.parameter`.

Makes a marker usable both bare (``Annotated[str, Body]``)
and as a call (``Annotated[str, Body("field")]``).

Current value: `Body`

#### `create_app`

```python
def create_app(root_module: type[object] | DynamicModule, *, debug: bool = False, adapter: AbstractHttpAdapter | None = None) -> Application
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
def Controller(prefix: str = '') -> Callable[[ClassT], ClassT]
```

Defined in `bustan.common.decorators.controller`.

Attach controller metadata to a class.

#### `Delete`

```python
def Delete(path: str = '/') -> Callable[[FunctionT], FunctionT]
```

Defined in `bustan.common.decorators.route`.

Return a decorator that registers a DELETE route.

#### `DynamicModule`

```python
class DynamicModule
```

Defined in `bustan.core.module.dynamic`.

Metadata overlay that compiles into a unique module instance.

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
def Get(path: str = '/') -> Callable[[FunctionT], FunctionT]
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

#### `Module`

```python
def Module(*, imports: Iterable[type[object] | DynamicModule] | None = None, controllers: Iterable[type[object]] | None = None, providers: Iterable[object | dict[str, Any]] | None = None, exports: Iterable[object] | None = None) -> Callable[[ClassT], ClassT]
```

Defined in `bustan.core.module.decorators`.

Attach module metadata to a class without performing registration.

#### `ModuleCycleError`

```python
class ModuleCycleError(InvalidModuleError)
```

Defined in `bustan.core.errors`.

Raised when a module import cycle is detected.

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

#### `Patch`

```python
def Patch(path: str = '/') -> Callable[[FunctionT], FunctionT]
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
def Post(path: str = '/') -> Callable[[FunctionT], FunctionT]
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
def Put(path: str = '/') -> Callable[[FunctionT], FunctionT]
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
