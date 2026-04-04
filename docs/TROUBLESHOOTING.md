# Troubleshooting

These are the most common framework-level errors you are likely to hit while wiring modules and handlers.

## `ModuleCycleError`

Cause: two modules import each other directly or indirectly.

Fix: move shared providers into a third module and have both feature modules import that shared module instead of each other.

## `ExportViolationError`

Cause: a module exports a provider it does not declare.

Fix: add the provider to the module's `providers` list before exporting it.

## `ProviderResolutionError`

Cause: a controller or provider depends on something the container cannot resolve from the current module graph.

Fix: confirm the dependency is decorated with `@injectable`, registered in a module, and exported from any module boundary it must cross.

## `ParameterBindingError`

Cause: route inputs cannot be converted from path, query, or JSON body data.

Fixes:

- make sure path parameter names match the handler parameter names
- send query values in a shape the annotation can coerce
- send a JSON object when binding multiple body fields
- keep body payload fields aligned with dataclass field names

## Guard Rejections

Cause: a guard returns a falsey value during request execution.

Fix: inspect the request state or headers the guard expects, or add an exception filter if you want a structured rejection payload instead of the default `403` response.

## Lifecycle Failures

Cause: a lifecycle hook raised during startup or shutdown.

Fix: keep hook logic thin, push external I/O behind providers, and surface required configuration errors early so they fail before the server starts accepting traffic.