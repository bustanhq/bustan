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

### `depends on request-scoped provider ...`

Cause: a longer-lived owner injects a request-scoped provider. The most common shape is a
controller declared without `scope=`, which makes it a singleton: it is built once and reused for
every request, so the first caller's request-local state would be served to every later caller.

Fix: declare the owner request-scoped, for example `@Controller("/account", scope=Scope.REQUEST)`
or `@Injectable(scope="request")`. Keep long-lived business services singleton and inject them
alongside the request-scoped provider. If the owner must stay singleton, pass the request-local
value into the method that needs it rather than holding it on the instance.

### `depends on durable-scoped provider ...`

Cause: a singleton owner injects a durable-scoped provider. The singleton captures whichever
partition was resolved first and then serves that tenant's instance to every other tenant.

Fix: declare the owner durable, request-scoped, or transient, so that it does not outlive the
partition it is reading.

### `requests framework-owned type Request ...`

Cause: a singleton or durable owner injects Starlette's `Request`. Both outlive the request, so
they would retain the first caller's headers, including its `Authorization` header.

Fix: only request-scoped and transient owners may inject `Request`. Move the request-derived
value into a request-scoped provider and inject that instead.

### `get_durable_context_key returned a ... which cannot be used as a cache key`

Cause: a durable provider's `get_durable_context_key` returned an unhashable value, such as a
list or a dict.

Fix: return a hashable key, for example a string or a tuple of strings.

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