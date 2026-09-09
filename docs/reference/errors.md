# Troubleshooting

These are the framework-level failures most likely to appear while wiring modules, controllers, providers, and request-time behavior.

## How To Read This Page

Every failure the framework raises is an exception exported from `bustan.errors`, and every one of those classes has an entry below, named exactly as it appears in the traceback. Find the class name first, then the condition inside the entry that matches the message text.

Most of these are refused while the application is built, before the first request is served. A graph with several problems is reported once with every reason listed under a single `The application cannot be built. N problems were found:` header, so fix them together rather than one deploy at a time.

## `InvalidModuleError`

Cause: a module declaration the framework cannot read, or a module graph whose declarations do not say what should happen.

Common conditions and fixes:

- `@Module can only decorate classes`, or `@Global can only decorate classes already decorated with @Module` - apply the decorators to a class, and apply `@Global` on top of `@Module`.
- `... is already decorated with @Module` - one class declares its imports, controllers, providers and exports exactly once. Merge the two declarations.
- `Module <field> must be an iterable of objects` - pass a list or tuple. A mapping is read as its keys, and a single provider definition dict must still be written inside a sequence: `providers=[{...}]`, not `providers={...}`.
- `Module <field> must be an ordered iterable of objects` - a `set` or `frozenset` does not preserve declaration order, and declaration order decides which of two competing declarations wins. Use a list or tuple.
- `... declares duplicate entries in <field>` - remove the repeat. A token listed twice says nothing about which entry is meant.
- `... imports X, which is not a decorated module` - `imports` takes modules, not providers. Put the provider in `providers`, or import the module that exports it.
- `... exports the module Y. A module is not a provider token: import it, and export the tokens it exports instead.` - see the `exports=[SomeModule]` case under [`ExportViolationError`](#exportviolationerror) below.
- `... imports both A and B, which export T from different modules` - two imported modules re-export one token from different origins and nothing in the declaration says which wins. Import one of them, provide the token locally, or export it from a single module.
- `Global modules A and B both export T` - a global export reaches every module, so nothing can choose between them. Export the token from one module only.
- `T is visible to M through D, which declares no provider for it` - a module exports a token it never bound. Declare it in that module's `providers`.
- `Could not build module M: ... A module the framework builds must accept no constructor arguments` - a module class that declares lifecycle hooks is built by the framework, which has nothing to pass a constructor. Move the dependencies into a provider the module's hooks resolve.
- `... is not a valid base module for dynamic registration` - the class passed to `DynamicModule` must itself be decorated with `@Module`.

`ModuleCycleError` and `ExportViolationError` are both subclasses of `InvalidModuleError`, so `except InvalidModuleError` catches every module-graph refusal at once.

## `ModuleCycleError`

Cause: two modules import each other directly or indirectly. The message prints the cycle as a path, so the shortest way to read it is to look for the module that appears at both ends.

Fix: move the shared providers into a third module and have both feature modules import that shared module instead of each other.

A cycle between *providers* rather than modules is reported as `Circular provider dependencies detected` under [`ProviderResolutionError`](#providerresolutionerror).

## `ExportViolationError`

Cause: a module's `exports` names a provider token the module neither declares nor receives. The message is `... exports T, but that provider is not available (neither provided nor imported)`.

Fix: a module may only export what it can supply, so give it one of the two ways of supplying it:

- declare the provider in that module's `providers` list, or
- import the module that exports the token, and re-export the same token.

Re-exporting a whole module is not one of the two. Writing the module class into `exports` raises `InvalidModuleError`, not this error, with the fix in the message: import the module, and export the tokens it exports. Writing the token instead is accepted:

```python
from bustan import Injectable, Module, create_app_context
from bustan.errors import InvalidModuleError


@Injectable()
class SharedService:
    pass


@Module(providers=[SharedService], exports=[SharedService])
class SharedModule:
    pass


@Module(imports=[SharedModule], exports=[SharedModule])
class RefusedCoreModule:
    pass


@Module(imports=[SharedModule], exports=[SharedService])
class CoreModule:
    pass


@Module(imports=[RefusedCoreModule])
class RefusedApp:
    pass


@Module(imports=[CoreModule])
class AcceptedApp:
    pass


try:
    create_app_context(RefusedApp)
except InvalidModuleError as error:
    print(error)

print(create_app_context(AcceptedApp).get(SharedService).__class__.__name__)
```

```text
RefusedCoreModule exports the module SharedModule. A module is not a provider token: import it, and export the tokens it exports instead.
SharedService
```

Do not add the module class to `providers` to satisfy either error. That registers the module class itself as a class provider, so `resolve(SharedModule)` hands back a bare module instance and none of the module's tokens are re-exported: the application builds and is wrong at runtime instead of refused at startup.

## `InvalidProviderError`

Cause: a `providers` entry the container cannot turn into a binding. Every message names the declaring module first, as `Invalid provider in M: ...`, because that is the file to edit.

Common conditions and fixes:

- `@Injectable can only decorate classes`, or `Unsupported provider scope` - the scope must be one of `singleton`, `request`, `transient` or `durable`.
- `... is not a class or a provider definition dict` - a `providers` entry is either a class or a `{"provide": ..., "use_*": ...}` dict.
- `unknown provider keys`, `the definition has no 'provide' key`, or `declares none of use_class, use_factory, use_value, use_existing` - a definition names exactly one `use_*` key beside `provide`.
- `... declares more than one of ...` - pick one binding form.
- `the 'provide' token ... cannot be used as a key` - a token must be hashable. Use a class, a string, or an `InjectionToken`.
- `... declares 'inject' beside '<key>', which takes no dependencies` - only `use_factory` takes an `inject` list.
- `... declares 'scope' beside '<key>', which cannot honour a lifetime of its own` - `use_value` is one object and `use_existing` borrows the lifetime of the token it points at, so neither can be given a scope.
- `... binds C as <scope>-scoped, but the class declares <scope> scope. A binding may narrow a declared scope, never widen it` - a `use_class` may bind a request-scoped class as transient, but not as a singleton. See [Binding Forms And Scope](../explanation/request-scope.md#binding-forms-and-scope).
- `... asks for a durable 'use_factory'` - a durable lifetime is partitioned by a `get_durable_context_key` hook, which only a class can carry. Use `use_class`.
- `... asks for a durable lifetime but declares no 'get_durable_context_key'`, or the hook is not a `classmethod` or `staticmethod` - the key selects the instance, so it must be derivable without one.
- `... and ... are equal but are not the same token, so one would silently take the other's binding` - two tokens in one module compare equal but are different objects or types, such as a `str` and a `StrEnum` member spelling the same value. Declare one of them under a distinct token.

## `InvalidControllerError`

Cause: a controller declaration the framework cannot serve.

Common conditions and fixes:

- `@Controller can only decorate classes`, `Unsupported controller scope`, or `Use either 'host' or 'hosts', not both`.
- `... is not decorated with @Controller` - every entry in a module's `controllers` list needs the decorator.
- `... declares scope 'durable', which a controller cannot have` - a durable instance is cached per context key and a controller is not partitioned that way. Declare a singleton, request or transient controller and keep the per-key state in a durable provider it injects.
- `... declares 'get_durable_context_key'` - the hook that partitions a durable provider is never called on a controller. Move it onto the durable provider that keeps the per-key state.

## `InvalidPipelineError`

Cause: a guard, pipe, interceptor, filter, or policy decorator that cannot be attached or cannot be built.

Common conditions and fixes:

- `@UseGuards`/`@UsePipes`/`@UseInterceptors`/`@UseFilters` `requires at least one component` - pass the components as arguments.
- `... can only decorate controller classes or handler callables` - the same applies to the policy decorators. Apply them to a controller class or one of its handler methods.
- `<Kind> C must be an instance, a no-argument class, or an @Injectable provider` - a class listed as a pipeline component is built with no arguments unless the container declares it. Register it in a module's `providers` when it needs dependencies.
- `Resolved <kind> C must inherit from <Base>` - the component resolved from the container is not of the type that stage expects.

## `ProviderResolutionError`

Cause: a dependency the container cannot find, cannot read, or cannot let its owner hold. This is the largest class, and the message text says which group a failure belongs to.

**The dependency cannot be found.**

- `C.__init__ parameter 'p' needs T, which M cannot see. Declare it in that module, import a module that exports it, or give the parameter a default` - the token is not visible to the module building the class. Confirm the dependency is decorated with `@Injectable()` when it should be container-managed, register it in a module's `providers` list, and export it from every module boundary it must cross.
- `Binding not found for T`, or `T is not available to M. Dependencies must come from the same module or an imported module export` - the same, reported at resolution rather than while planning.
- `M is not part of the application container` - the module passed to `resolve()` is not in the graph the application was built from.

**The constructor cannot be read.**

- `... parameter 'p' has no type annotation, so there is nothing to inject` - annotate the parameter or give it a default.
- `Could not evaluate the annotation of ... parameter 'p'` - a string annotation names something that is not importable at the point the class is defined, usually a `TYPE_CHECKING`-only import.
- `... is annotated with a union that does not name exactly one type to inject` - a union is only injectable when exactly one member is a token, as in `T | None`.
- `... carries N Inject markers, so the token to inject is ambiguous` - one `Inject` per parameter.
- `... is variadic and cannot be injected` - `*args` and `**kwargs` cannot be supplied.
- `... is positional-only and follows a parameter left to its default, so it cannot be supplied`.

**The owner would outlive what it holds.** These are the scope rules, and each message names the owner, the parameter, and the state it reaches. [explanation/request-scope.md](../explanation/request-scope.md) states the rule the messages enforce.

- `... depends on request-scoped provider P, which can only be injected into an owner that lives no longer than it does` - the direct refusal. Move the consumer to request scope, move the request-local dependency into a request-scoped collaborator, or pass the request-derived data as a method argument instead of constructor state. The same message names a durable provider when a singleton reaches durable scope.
- `... depends on X, which keeps no instance of its own and reaches <state>` - the transitive refusal. `X` is a transient or a `use_existing` alias, so it carries whatever it reaches into whoever holds it. The phrase after `reaches` names the provider whose own lifetime is the reason.
- `... requests framework-owned type HttpRequest, which can only be injected into a request-scoped or transient owner` - `HttpRequest`, `HttpResponse` and the serving transport's own request and response types all read this way; the `REQUEST` and `RESPONSE` tokens say `requests the REQUEST token` instead and mean the same thing. A singleton or durable owner outlives the request.
- `... requests INQUIRER, which can only be injected into a transient provider` - `INQUIRER` names the class a provider is being built for, so only a provider rebuilt per consumer can carry it.

**The state asked for does not exist yet, or no longer does.**

- `... asks for the request being served, and no request is being served`, or `... asks for the response being assembled, and none is being assembled` - resolving request state outside a request, usually from a startup hook or a bare `container.resolve()`.
- `Request-scoped provider P requires an active request` - the same, reached through a provider rather than a token.
- `... asks for the running application, which is only available once one is running`.
- `... asks for INQUIRER, which names the class one provider is being built for and has no value outside a nested construction`.
- `Durable provider P must implement the DurableProvider protocol with a 'get_durable_context_key' classmethod`.
- `... is an async factory and cannot be called during synchronous resolution. Initialize the application before resolving what it provides` - run `await context.init()`, or start the application, before resolving a token whose factory is asynchronous.
- `Circular provider dependencies detected: <path>` - two providers depend on each other. The path names the cycle; break it by moving the shared work into a third provider.

**An override cannot be applied.** These come from `bustan.testing`.

- `T is not registered in <where>` - the token the override names is not declared where the override looked.
- `T is registered in more than one module (...); name the one to override it in as 'module'`.
- `T cannot be overridden while the application is running` - an override replaces a provider for the whole application, including the instances already built from it, so register every override before startup.

## `RouteDefinitionError`

Cause: route metadata that is malformed, duplicated, or that the adapter cannot serve.

Common conditions and fixes:

- `... is missing an HTTP route decorator` - add `@Get`, `@Post`, `@Put`, `@Patch`, or `@Delete` to each public handler method. A controller method without one is refused rather than served, so keep helpers private or move them into a provider.
- `Route decorators can only decorate callables`, or `... already has route metadata for <METHOD> <path>` - one route per handler. Declare a second handler for a second route.
- `Route method must be a string`, `cannot be empty`, or `contains invalid characters`.
- `<Kind> must be a string` or `cannot be empty` - a controller prefix and a route path are both normalized through the same check.
- `Use either 'host' or 'hosts', not both`.
- `... defines duplicate route <METHOD> <path> on handlers A and B`, `Duplicate application route ...`, or `Conflicting route path pattern for ...` - two handlers claim one path. The last of these fires when the paths differ only by parameter name, such as `/users/{id}` and `/users/{user_id}`, which match the same requests.
- `Duplicate version-neutral route ...` or `Overlapping versions [...] for route ...` - two versioned declarations of one path answer the same version.
- `... does not support host routing for ...`, `raw body access`, or `streaming responses` - the route asks for a capability the configured adapter does not advertise. See [reference/adapters.md](../reference/adapters.md).
- `... declares @Public together with auth/roles/permissions at the <level> level` - remove one of the contradictory declarations.
- `... uses raw response mode and cannot apply interceptor I because it mutates the response body` - a raw response is handed to the client as written, so an interceptor that rewrites the body has nothing to rewrite.

## `ParameterBindingError`

Cause: route inputs cannot be compiled from a handler signature, or cannot be converted from path, query, headers, cookies, files, or JSON body data.

Common fixes:

- make sure path parameter names match the handler parameter names
- send query values in a shape the annotation can coerce
- send a JSON object when binding multiple body fields
- keep body payload fields aligned with dataclass or Pydantic model fields in name *and* in type: a required field the body omits, a key the model does not declare, and a value that is not the declared type are all refused, and the wording of each refusal is below
- use `Annotated[..., Param | Query | Body | Header | ...]` when inference is ambiguous
- avoid `*args` and `**kwargs` in controller handlers, which are refused as `uses unsupported variadic parameter`
- `Could not resolve type hints for C.handler` means an annotation on the handler is not importable where the class is defined, the same condition as the annotation failures under `ProviderResolutionError`
- `... requires an explicit binding marker in strict mode`, or `... is ambiguous in explicit mode` - `binding_mode="strict"` turns an inferred binding into a startup-time failure, which is the point of it; annotate the parameter with the marker you meant

**A body that does not fit its model is refused, not repaired.** The caller sees `400` with the title `Bad Request`, and the `detail` opens with `Could not bind request body '<parameter>' to <Type>:` and then names what is wrong. The messages below were served by a handler taking `payload: Note`, where `Note` is a dataclass with `title: str`, `count: int`, `tags: list[str]` and `inner: Inner | None`, and `Inner` declares `depth: int`.

**A field whose value is not its declared type is refused, and the message names the type it wanted.** Posting `{"title": "Ada", "count": "7"}`:

```text
Could not bind request body 'payload' to Note: field of the wrong type 'count' (wanted int)
```

**A problem inside a nested object or a list element is named where it sits.** The path in the message is the route to the offending value, not just the top-level field, so `inner.depth` is the `depth` key of the `inner` object and `tags[1]` is the second element of `tags`. Posting `{"title": "Ada", "count": 2, "inner": {"depth": "3"}}` and then `{"title": "Ada", "count": 2, "tags": ["a", 2]}`:

```text
Could not bind request body 'payload' to Note: field of the wrong type 'inner.depth' (wanted int)
Could not bind request body 'payload' to Note: field of the wrong type 'tags[1]' (wanted str)
```

**Every problem in one body is answered in one response.** Missing fields, unexpected fields and wrong types are composed into a single sentence, so a `400` is the whole list rather than the first item on it and a caller repairs the body in one attempt instead of one deploy per problem. Posting `{"colour": "red", "count": "7"}`:

```text
Could not bind request body 'payload' to Note: missing required field 'title', unexpected field 'colour' and field of the wrong type 'count' (wanted int)
```

The `reason` field carries the same content for a caller that would rather parse than read: names within one kind of problem are separated by commas and the kinds by semicolons, so the body above also reports `missing required field: title; unexpected field: colour; field of the wrong type: count wanted int`.

**A convertible mismatch is refused, not coerced.** `{"count": "7"}` for a field declared `int` is the `400` quoted above, not the number `7` handed to the handler. A query parameter would have coerced it, because a query string carries only text and reading `7` out of `"7"` is the only thing to do there. A JSON body carries real types, so a caller that had `7` and sent `"7"` made a mistake worth being told about. A reader migrating from 1.x meets this one first.

**A `True` for a field declared `int` is refused**, even though `bool` is a subclass of `int` in Python. Posting `{"title": "Ada", "count": true}` is answered with the same `field of the wrong type 'count' (wanted int)` as the string was: a document that carried `true` carried no number, and the alternative is `true` arriving at arithmetic as the number one.

By default, unhandled binding errors become HTTP `400` responses with structured `field` and `source` metadata.

## `RequestBodyTooLargeError`

Cause: the request carried more body bytes, or more uploaded parts, than the limits the application serves under allow. The caller sees `413` with the title `Content Too Large`, and the `detail` names the figure that was measured against the figure that was allowed, in one of four shapes:

- `The request body declares N bytes, over the M byte limit`, or `The upload declares ...` - the refusal came from the declared `Content-Length` and the body was never read, so a request that announces a large body is refused before it costs anything to receive. The two wordings separate the ordinary body bound from the multipart one.
- `The request body exceeds the M byte limit` - the body was sent without a declared length and the adapter stopped reading at the byte that crossed the limit.
- `The request body carries N bytes, over the M byte limit` - the same undeclared body, refused after it was read in full because the adapter serving it bounds nothing itself. What this decides is what the handler is handed, not what receiving the request cost.
- `The request uploads N files for 'field', over the M file limit` - a multipart form bound more parts to one parameter than `max_upload_files` allows.

Fix: send less, or raise the bound the application serves under. The three bounds are `max_body_bytes` for an ordinary body, `max_upload_bytes` for a multipart one and `max_upload_files` for the number of parts, and they are set together:

```python
from bustan import Controller, Module, Post, RequestLimits, create_app


@Controller("/uploads")
class UploadsController:
    @Post("/")
    def create(self, title: str) -> dict[str, str]:
        return {"title": title}


@Module(controllers=[UploadsController])
class AppModule:
    pass


app = create_app(AppModule, request_limits=RequestLimits(max_body_bytes=4 * 1024 * 1024))
print(app.__class__.__name__)
```

```text
Application
```

Every bound has a finite default, so an application that configures nothing still refuses something; `None` removes one bound for a deployment that has measured that it needs to.

Catch the class to answer the refusal yourself. A filter declaring `exception_types = (RequestBodyTooLargeError,)` is preferred over the framework's own, which is what renders the `413` when no application filter answers it.

## `RequestTimeoutError`

Cause: one request ran longer than `timeout_seconds`, the wall clock the application allows a single request, and was abandoned. The caller sees `504` with the title `Gateway Timeout`; the message naming the budget goes to the log rather than to the caller, because it tells an unauthenticated caller how long to hold a connection to exhaust the workers.

Fix: make the request faster, or give it longer:

```python
from bustan import Controller, Get, Module, RequestLimits, create_app


@Controller("/reports")
class ReportsController:
    @Get("/")
    def index(self) -> dict[str, str]:
        return {"reports": "all"}


@Module(controllers=[ReportsController])
class AppModule:
    pass


app = create_app(AppModule, request_limits=RequestLimits(timeout_seconds=60.0))
print(app.__class__.__name__)
```

```text
Application
```

A synchronous handler is a special case. It runs on a thread, Python cannot interrupt one, and so the budget is enforced for it only once it returns. What bounds a synchronous handler that never returns is `sync_handler_threads`, which caps how many of them may occupy threads at the same time; a timeout that never fires on a blocking handler is that distinction rather than a broken limit.

Catch the class to answer the timeout with a status of your own - a `503` while the application sheds load reads differently to a caller than the framework's `504`:

```python
from bustan import ExceptionFilter, ExecutionContext, HttpResponse
from bustan.errors import RequestTimeoutError


class BusyFilter(ExceptionFilter):
    exception_types = (RequestTimeoutError,)

    async def catch(self, exc: Exception, context: ExecutionContext) -> object:
        return HttpResponse.json({"detail": "Busy, try again"}, status_code=503)


print(BusyFilter.exception_types[0].__name__)
```

```text
RequestTimeoutError
```

## `BadRequestException`

Cause: a request failed explicit validation. The built-in pipes raise it for a value they cannot parse - `Validation failed (integer expected)` and its siblings for `float`, `boolean`, `UUID` and enum members - and application code raises it for validation the framework cannot do itself.

Fix: correct the request. Like `ParameterBindingError`, it carries `field`, `source` and `reason`, renders as a `400`, and is the exception to raise from a pipe or a handler when you want that shape without writing a filter.

It is also the `400` member of the `HttpException` family below, so its response carries the problem type `https://bustan.dev/problems/bad-request` and the code `bad-request` alongside those fields.

## `HttpException`

Cause: nothing in the framework raises it directly. It is the base class of the fifteen status exceptions below, which an application raises from a handler, a pipe, an interceptor or a filter to answer a caller with a status the route would not otherwise return.

Each subclass fixes three values that are a published contract, so a client may branch on them and a runbook may grep for them:

| Class | Status | `type` | `code` |
| --- | --- | --- | --- |
| `BadRequestException` | 400 | `https://bustan.dev/problems/bad-request` | `bad-request` |
| `UnauthorizedException` | 401 | `https://bustan.dev/problems/unauthorized` | `unauthorized` |
| `ForbiddenException` | 403 | `https://bustan.dev/problems/forbidden` | `forbidden` |
| `NotFoundException` | 404 | `https://bustan.dev/problems/not-found` | `not-found` |
| `MethodNotAllowedException` | 405 | `https://bustan.dev/problems/method-not-allowed` | `method-not-allowed` |
| `ConflictException` | 409 | `https://bustan.dev/problems/conflict` | `conflict` |
| `ContentTooLargeException` | 413 | `https://bustan.dev/problems/content-too-large` | `content-too-large` |
| `UnsupportedMediaTypeException` | 415 | `https://bustan.dev/problems/unsupported-media-type` | `unsupported-media-type` |
| `UnprocessableEntityException` | 422 | `https://bustan.dev/problems/unprocessable-entity` | `unprocessable-entity` |
| `TooManyRequestsException` | 429 | `https://bustan.dev/problems/too-many-requests` | `too-many-requests` |
| `InternalServerErrorException` | 500 | `https://bustan.dev/problems/internal-server-error` | `internal-server-error` |
| `NotImplementedException` | 501 | `https://bustan.dev/problems/not-implemented` | `not-implemented` |
| `BadGatewayException` | 502 | `https://bustan.dev/problems/bad-gateway` | `bad-gateway` |
| `ServiceUnavailableException` | 503 | `https://bustan.dev/problems/service-unavailable` | `service-unavailable` |
| `GatewayTimeoutException` | 504 | `https://bustan.dev/problems/gateway-timeout` | `gateway-timeout` |

The message becomes the problem's `detail`, except at 500 and above: those statuses report a fault in the application rather than anything the caller can act on, and their messages routinely name internal detail, so the caller is shown `Internal server error` and the message is kept in the log. Passing `headers=` adds response headers, which is how a 401 states a challenge other than the default.

An exception that is not one of these and not otherwise modelled still renders as a `500` whose `type` is `about:blank` and which carries no `code`, because that is what the standard defines that value to mean: a problem with no semantics beyond its status.

The framework answers with these documents too, without an application raising anything. A path no route answers and a version nothing serves both produce the `NotFoundException` document, and a method no route answers produces the `MethodNotAllowedException` one with an `Allow` header; see [reference/routing.md](../reference/routing.md#refusals-before-a-handler-runs). So a `404` carrying `not-found` does not tell you whether a handler raised it or the router did, and the two are told apart by `detail`, which an application sets and the router leaves as the status reason.

Fix: nothing to fix. Raise the subclass whose status says what happened.

## `UnauthorizedException`

Cause: raised by an application to answer `401` when the request carries no usable credentials.

The response carries a `WWW-Authenticate` challenge, defaulting to `Bearer`, because a 401 without one tells a client that it must authenticate without telling it how. Pass `headers={"WWW-Authenticate": ...}` to state the scheme the application really uses.

Fix: present credentials. A caller the application has already identified and is refusing anyway is answered with `ForbiddenException` instead, because presenting the same identity again would change nothing.

## `ForbiddenException`

Cause: raised by an application to answer `403` when an identified caller is not allowed to do this.

Fix: say what is refused, never why in terms of the application's own roles or permissions. The caller being refused is the one party those names must not reach.

## `NotFoundException`

Cause: raised by an application to answer `404` when the addressed resource does not exist. Before this class existed a 404 was only reachable by returning a raw response, outside the framework's error model.

Fix: check the identifier in the path.

## `MethodNotAllowedException`

Cause: raised by an application to answer `405` when the resource exists but not for this method.

Fix: use a method the route serves.

## `ConflictException`

Cause: raised by an application to answer `409` when the request contradicts the resource's current state, such as a create that collides with an existing record or an update against a stale version.

Fix: re-read the resource and retry against what it says now.

## `ContentTooLargeException`

Cause: raised by an application to answer `413` when the request body is larger than the route accepts.

The framework's own body limit answers `413` through its request-limit filter rather than through this class, so a refusal that names no `code` at all came from that limit and not from application code; see [`RequestBodyTooLargeError`](#requestbodytoolargeerror).

Fix: send a smaller body, or raise the limit the deployment sets.

## `UnsupportedMediaTypeException`

Cause: raised by an application to answer `415` when the body is in a format the handler cannot read.

Fix: send a `Content-Type` the route accepts.

## `UnprocessableEntityException`

Cause: raised by an application to answer `422` when a well-formed body asks for something impossible.

Fix: a body the framework could not read at all is a `400` reported through `BadRequestException`; this status is for one that parsed and then failed a rule the application enforces, so the rule is what to look at.

## `TooManyRequestsException`

Cause: raised by an application to answer `429` when the caller has exceeded a rate it is held to. The built-in throttler produces its own `429` through `GuardRejectedError` rather than through this class.

Fix: slow down, or raise the limit.

## `InternalServerErrorException`

Cause: raised by an application to answer `500` when it cannot serve the request.

The message reaches the log and not the caller, so write it for whoever is on call.

Fix: read the log line, not the response body.

## `NotImplementedException`

Cause: raised by an application to answer `501` when the route exists but the behaviour is not written yet.

Fix: nothing the caller can do. It marks unfinished work on the server.

## `BadGatewayException`

Cause: raised by an application to answer `502` when a service it depends on answered unusably.

Fix: the fault is downstream. The message names which service, in the log.

## `ServiceUnavailableException`

Cause: raised by an application to answer `503` when it is up but cannot serve requests now, such as while draining or while a dependency is being replaced.

Fix: retry later. Pass `headers={"Retry-After": ...}` to say how much later.

## `GatewayTimeoutException`

Cause: raised by an application to answer `504` when a service it depends on did not answer in time. The framework's own request timeout answers `504` through its request-limit filter rather than through this class; see [`RequestTimeoutError`](#requesttimeouterror).

Fix: the fault is downstream, or the budget is too small for it.

## `GuardRejectedError`

Cause: a guard returned a falsey value or raised `GuardRejectedError` during request execution. The built-in guards raise it as `Policy denied: missing roles ...` or `Policy denied: missing permissions ...`, and as `Authentication required` through the subclass `AuthenticationRequiredError` below.

**The caller is not shown any of that.** The rejection renders as a `403` whose `detail` is the fixed string `Forbidden`, a `401` when it was refused for want of an identity, or a `429` whose `detail` is `Too Many Requests` when the request was refused for exceeding a rate limit. The message would otherwise hand an unauthenticated caller the dotted class path of the guard that refused it, the identifier of the authentication strategy the route expects, or the roles and permissions it does not hold, none of which it can act on and each of which narrows the search for someone probing the application.

The message is written to the log instead, at `WARNING` on the `bustan.pipeline.guards` logger, in this shape:

```
Request rejected [correlation_id=1f9c0b1e4c1d4c8f9a2b6d7e8f0a1b2c]: Guard app.security.guards.InternalOnlyGuard blocked the request
```

The identifier is the request's own, the same value `request_context_id(request).value` returns anywhere else in that request, so a rejection in the log can be joined to everything else recorded for the request that caused it. A guard rejection is the only thing that mints it when nothing else has, so it is always present on this line.

Fix: read the log line for the reason, then inspect the request state or headers the guard expects. Add an exception filter for `GuardRejectedError` if you want a rejection payload of your own shape; a filter sees the full message, so decide deliberately what of it you put in the response.

## `AuthenticationRequiredError`

Cause: a route needing an authenticated caller was reached by a request carrying no identity. It is a subclass of `GuardRejectedError`, so `except GuardRejectedError` still catches it, and it refuses exactly the requests that were refused before it existed.

What it changes is the answer. A refusal for want of an identity renders as a `401` carrying `WWW-Authenticate: Bearer`, which is what an OAuth or OIDC client waits for before starting a refresh; a caller the application has identified and refused anyway still renders as a `403` with no challenge. The `detail` on both is the status reason and nothing else.

Fix: send credentials the route's authentication strategy accepts. A `401` on a request that did send them means the strategy rejected them, which the log line records.

## `AuthenticatorRegistryError`

Cause: a route carrying an authentication policy cannot reach a usable authenticator registry. It is not a `GuardRejectedError` and never reports a caller: it reports the application.

It is raised while the application is being built, from the route compiler, in two conditions:

- `... authenticates its callers, and no provider for AUTHENTICATOR_REGISTRY is visible to M` - no module visible to the route declares the registry. Declare it in that module's `providers`, or import a module that exports it.
- `... is built by an async factory, which the guard that reads it cannot await` - the guard resolves the registry synchronously in the middle of a request, so a `use_factory` that is a coroutine function can never be read. Declare it with `use_value`, or build it with a synchronous factory.

It is also raised at request time, and rendered as a masked `500`, for the misconfiguration the compiler cannot see: a registry that resolves but holds no authenticator under the strategy the route names, reported as `Unknown authenticator '<strategy>'` on the `bustan.pipeline.guards` logger at `ERROR`.

Fix: wire the registry. Before this error existed all three conditions reached the caller as a `403`, so an authenticated route that refused every caller looked exactly like a caller sending a wrong password.

## `LifecycleError`

Cause: a lifecycle hook raised during startup or shutdown. The message names the hook, as `Lifecycle hook M.on_module_init failed: ...` for a module hook and `Provider lifecycle hook T.on_module_destroy failed: ...` for a provider one, and keeps the original exception as its `__cause__`.

Fix: keep hook logic thin, push external I/O behind providers, and surface required configuration errors early so they fail before the server starts accepting traffic.

A startup failure is raised on its own, after the framework has torn down whatever it had already built; a hook that also failed while undoing it is attached to that exception as a note.

Shutdown is different, because every teardown stage runs to completion even when a hook fails. One failed teardown hook is raised on its own. **More than one is raised together as an `ExceptionGroup` that is also a `LifecycleError`**, so `except LifecycleError` still catches it, and `except* LifecycleError` reads the members. Each member names one failed hook and keeps its own `__cause__`, so nothing is lost to the aggregation:

```python
import asyncio

from bustan import Injectable, Module, create_app_context
from bustan.errors import LifecycleError


@Injectable()
class FirstSink:
    async def on_module_destroy(self) -> None:
        raise RuntimeError("first sink would not close")


@Injectable()
class SecondSink:
    async def on_module_destroy(self) -> None:
        raise RuntimeError("second sink would not close")


@Module(providers=[FirstSink, SecondSink])
class AppModule:
    pass


async def main() -> None:
    context = create_app_context(AppModule)
    await context.init()
    try:
        await context.close()
    except* LifecycleError as group:
        for error in group.exceptions:
            print(error, "caused by", error.__cause__)


asyncio.run(main())
```

```text
Provider lifecycle hook SecondSink.on_module_destroy failed: second sink would not close caused by second sink would not close
Provider lifecycle hook FirstSink.on_module_destroy failed: first sink would not close caused by first sink would not close
```

Both hooks ran even though the first one raised, and the members arrive in teardown order, which reverses construction order.

[reference/lifecycle.md](../reference/lifecycle.md) documents the stages, the ordering, and the failure contract in full.

`bustan.testing` also raises it directly, as `The application was built without a lifecycle manager`, when a testing module is asked to start or stop an application built without one.

## `BustanError`

Cause: nothing raises it. It is the base class every other error on this page inherits from, so `except BustanError` catches any framework refusal and nothing else.

Use it at an application boundary where the distinction between a bad module graph and a bad request does not matter. Anywhere the distinction does matter, catch the specific class: `BustanError` also catches `BadRequestException` and `GuardRejectedError`, which are ordinary request outcomes rather than defects.

## When You Need More Visibility

Prefer public inspection helpers over private container internals:

- `app.snapshot_routes()` for deterministic route shape inspection
- `app.diff_routes(previous_snapshot)` for route drift checks
- `DiscoveryModule` plus `DiscoveryService` for runtime module, provider, and route discovery
