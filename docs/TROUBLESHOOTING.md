# Troubleshooting

These are the framework-level failures most likely to appear while wiring modules, controllers, providers, and request-time behavior.

## `ModuleCycleError`

Cause: two modules import each other directly or indirectly.

Fix: move shared providers into a third module and have both feature modules import that shared module instead of each other.

## `ExportViolationError`

Cause: a module exports a provider it does not declare.

Fix: add the provider to the module's `providers` list before exporting it.

## `ProviderResolutionError`

Cause: a controller or provider depends on something the container cannot resolve from the current module graph.

Common fixes:

- confirm the dependency is decorated with `@Injectable()` when it should be container-managed
- register the dependency in a module `providers` list
- export it from any module boundary it must cross
- avoid injecting request-scoped providers into singleton providers or singleton controllers

If the missing dependency is request-local, the consumer usually needs to move to request scope or accept request-derived data as a method argument instead.

## `RouteDefinitionError`

Cause: a controller method was compiled without a valid HTTP route decorator or uses an unsupported handler shape.

Common fixes:

- add `@Get`, `@Post`, `@Put`, `@Patch`, or `@Delete` to each handler method
- avoid `*args` and `**kwargs` in controller handlers
- keep route definitions on instance methods, not free functions

## `ParameterBindingError`

Cause: route inputs cannot be converted from path, query, headers, files, or JSON body data.

Common fixes:

- make sure path parameter names match the handler parameter names
- send query values in a shape the annotation can coerce
- send a JSON object when binding multiple body fields
- keep body payload fields aligned with dataclass or Pydantic model fields
- use `Annotated[..., Param | Query | Body | Header | ...]` when inference is ambiguous
- enable `binding_mode="strict"` when you want startup-time failures instead of inferred guesses

By default, unhandled binding errors become HTTP `400` responses with structured `field` and `source` metadata.

## Guard Rejections

Cause: a guard returned a falsey value or raised `GuardRejectedError` during request execution.

Fix: inspect the request state or headers the guard expects, or add an exception filter if you want a structured rejection payload instead of the default `403` response.

## Lifecycle Failures

Cause: a lifecycle hook raised during startup or shutdown.

Fix: keep hook logic thin, push external I/O behind providers, and surface required configuration errors early so they fail before the server starts accepting traffic.

Failures during bootstrap are wrapped in `LifecycleError`.

## When You Need More Visibility

Prefer public inspection helpers over private container internals:

- `app.snapshot_routes()` for deterministic route shape inspection
- `app.diff_routes(previous_snapshot)` for route drift checks
- `DiscoveryModule` plus `DiscoveryService` for runtime module, provider, and route discovery