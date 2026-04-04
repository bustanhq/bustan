# API Reference

This document is generated from docstrings in the stable public modules.
Regenerate it with `uv run python scripts/generate_api_reference.py`.

Stable modules:
- `star`
- `star.testing`
- `star.errors`

## `star`

Supported public API for the star package.

### Import

```python
from star import __version__, controller, create_app, get, injectable, module
from star import ExceptionFilter, Guard, Interceptor, Pipe
```

### Exports

#### `__version__`

Installed distribution version string for the star package.

Runtime behavior: resolved from the installed distribution metadata, or from local project metadata when running from a source checkout.

#### `ExceptionFilter`

```python
class ExceptionFilter
```

Defined in `star.pipeline.filters`.

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

#### `Guard`

```python
class Guard
```

Defined in `star.pipeline.guards`.

Base class for authorization and policy gates.

##### Methods

- `can_activate(self, context: RequestContext) -> bool`
  Return True to allow request execution to continue.

#### `Interceptor`

```python
class Interceptor
```

Defined in `star.pipeline.interceptors`.

Base class for around-handler behaviors.

##### Methods

- `intercept(self, context: HandlerContext, call_next: CallNext) -> object`
  Wrap handler execution and optionally transform the result.

#### `Pipe`

```python
class Pipe
```

Defined in `star.pipeline.pipes`.

Base class for parameter transformation and validation.

##### Methods

- `transform(self, value: object, context: ParameterContext) -> object`
  Return the transformed parameter value passed to the handler.

#### `bootstrap`

```python
def bootstrap(root_module: type) -> Starlette
```

Defined in `star.application`.

Compatibility alias for create_app().

#### `controller`

```python
def controller(prefix: str = '') -> Callable[[ClassT], ClassT]
```

Defined in `star.decorators`.

Attach controller metadata to a class.

#### `create_app`

```python
def create_app(root_module: type) -> Starlette
```

Defined in `star.application`.

Build a Starlette application from a decorated root module.

#### `delete`

```python
def delete(path: str = '/') -> Callable[[FunctionT], FunctionT]
```

Defined in `star.decorators`.

Return a decorator that registers a DELETE route.

#### `get`

```python
def get(path: str = '/') -> Callable[[FunctionT], FunctionT]
```

Defined in `star.decorators`.

Return a decorator that registers a GET route.

#### `injectable`

```python
def injectable(target: ClassT | None = None, *, scope: ProviderScope | str = ProviderScope.SINGLETON) -> ClassT | Callable[[ClassT], ClassT]
```

Defined in `star.decorators`.

Mark a class as a DI-managed provider with the selected scope.

#### `module`

```python
def module(*, imports: Iterable[type[object]] | None = None, controllers: Iterable[type[object]] | None = None, providers: Iterable[type[object]] | None = None, exports: Iterable[type[object]] | None = None) -> Callable[[ClassT], ClassT]
```

Defined in `star.decorators`.

Attach module metadata to a class without performing registration.

#### `patch`

```python
def patch(path: str = '/') -> Callable[[FunctionT], FunctionT]
```

Defined in `star.decorators`.

Return a decorator that registers a PATCH route.

#### `post`

```python
def post(path: str = '/') -> Callable[[FunctionT], FunctionT]
```

Defined in `star.decorators`.

Return a decorator that registers a POST route.

#### `put`

```python
def put(path: str = '/') -> Callable[[FunctionT], FunctionT]
```

Defined in `star.decorators`.

Return a decorator that registers a PUT route.

#### `use_filters`

```python
def use_filters(*filters: object) -> Callable[[DecoratedT], DecoratedT]
```

Defined in `star.decorators`.

Attach one or more exception filters to a controller or handler.

#### `use_guards`

```python
def use_guards(*guards: object) -> Callable[[DecoratedT], DecoratedT]
```

Defined in `star.decorators`.

Attach one or more guards to a controller or handler.

#### `use_interceptors`

```python
def use_interceptors(*interceptors: object) -> Callable[[DecoratedT], DecoratedT]
```

Defined in `star.decorators`.

Attach one or more interceptors to a controller or handler.

#### `use_pipes`

```python
def use_pipes(*pipes: object) -> Callable[[DecoratedT], DecoratedT]
```

Defined in `star.decorators`.

Attach one or more pipes to a controller or handler.

## `star.testing`

Supported testing helpers for the star package.

### Import

```python
from star.testing import create_test_app, create_test_module, override_provider
```

### Exports

#### `create_test_app`

```python
def create_test_app(root_module: type[object], *, provider_overrides: Mapping[type[object], object] | None = None) -> Starlette
```

Defined in `star.testing.builder`.

Create an application and apply any requested provider overrides.

#### `create_test_module`

```python
def create_test_module(*, name: str = 'TestModule', imports: Iterable[type[object]] | None = None, controllers: Iterable[type[object]] | None = None, providers: Iterable[type[object]] | None = None, exports: Iterable[type[object]] | None = None) -> type[object]
```

Defined in `star.testing.builder`.

Create a throwaway decorated module for isolated tests.

#### `override_provider`

```python
def override_provider(target: Starlette | ContainerAdapter, provider_cls: type[ResolvedT], replacement: ResolvedT, *, module_cls: type[object] | None = None) -> Iterator[None]
```

Defined in `star.testing.overrides`.

Temporarily replace a provider for the duration of a context block.

## `star.errors`

Public exception types for the star package.

### Import

```python
from star.errors import ProviderResolutionError, RouteDefinitionError, StarError
```

### Exports

#### `ExportViolationError`

```python
class ExportViolationError(InvalidModuleError)
```

Defined in `star.errors`.

Raised when a module exports a provider it does not declare.

#### `GuardRejectedError`

```python
class GuardRejectedError(StarError)
```

Defined in `star.errors`.

Raised when a guard blocks request execution.

#### `InvalidControllerError`

```python
class InvalidControllerError(StarError)
```

Defined in `star.errors`.

Raised when a controller declaration is invalid.

#### `InvalidModuleError`

```python
class InvalidModuleError(StarError)
```

Defined in `star.errors`.

Raised when module declarations or imports are invalid.

#### `InvalidPipelineError`

```python
class InvalidPipelineError(StarError)
```

Defined in `star.errors`.

Raised when pipeline decorators or components are invalid.

#### `InvalidProviderError`

```python
class InvalidProviderError(StarError)
```

Defined in `star.errors`.

Raised when a provider declaration is invalid.

#### `LifecycleError`

```python
class LifecycleError(StarError)
```

Defined in `star.errors`.

Raised when application lifecycle hooks fail.

#### `ModuleCycleError`

```python
class ModuleCycleError(InvalidModuleError)
```

Defined in `star.errors`.

Raised when a module import cycle is detected.

#### `ParameterBindingError`

```python
class ParameterBindingError(StarError)
```

Defined in `star.errors`.

Raised when request parameters cannot be bound.

#### `ProviderResolutionError`

```python
class ProviderResolutionError(StarError)
```

Defined in `star.errors`.

Raised when dependency resolution fails.

#### `RouteDefinitionError`

```python
class RouteDefinitionError(StarError)
```

Defined in `star.errors`.

Raised when route metadata is malformed or duplicated.

#### `StarError`

```python
class StarError(Exception)
```

Defined in `star.errors`.

Base exception for the framework.
