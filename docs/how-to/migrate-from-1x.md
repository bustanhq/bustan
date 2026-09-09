# Migrating From 1.x To 2.0

2.0 is a clean break. The framework carries no compatibility shim for a construct it
changed, so an application written against 1.x fails at import, at build, at the first
request that reaches a route - or, for one construct, not at all. This guide is what
stands in for those shims, together with [`bustan doctor`](../reference/cli.md#bustan-doctor), which
finds the half of the migration that leaves a trace in your source.

Read the second half of this guide even if the doctor reports nothing. **A clean scan
does not mean a finished migration.** The changes it cannot see are the ones that change
what your application answers rather than whether it starts - and one of them changes
nothing at all until you look, because it silently stops two of your lifecycle hooks
from running.

This guide was written by taking a small 1.x application, running it on `1.1.0`, running
it on 2.0, and recording every difference. What follows is that list, not a rewritten
changelog.

## What Did Not Change

Nothing was removed from the supported public surface. Measured against `1.1.0`:

| Module | 1.1.0 | 2.0 | Removed |
| --- | --- | --- | --- |
| `bustan` | 89 exports | 153 exports | none |
| `bustan.errors` | 13 exports | 32 exports | none |
| `bustan.testing` | 7 exports | 9 exports | none |

```bash
python -c "import bustan; print(len(bustan.__all__))"
```

Every name a 1.x application imported from `bustan`, `bustan.errors` or
`bustan.testing` still imports from the same place in 2.0. That is the whole of the
good news, and it is worth stating first because it locates the work: what breaks is
what a 1.x application imported from *inside* the package, and what it assumed about
behaviour. [reference/stability.md](../reference/stability.md) says which modules those three are and why the
rest were free to move.

## The Order To Work In

1. Install 2.0 with the transport you serve on. `uv add bustan` installs no web server;
   `uv add 'bustan[starlette]'` installs the adapter this package ships.
2. Run `bustan doctor` over your source and fix everything it reports.
3. Rename your lifecycle hooks. It is the one silent break, so do it before you have a
   running application to distract you:
   `grep -rn "def on_app_startup\|def on_app_shutdown" .`
4. Work the rest of the by-hand list, which is everything the doctor cannot see.
5. Start the application. A refusal at build time is the container telling you about a
   defect 1.x served rather than reported; the list below names the ones that reach it.
6. Re-run your own tests against the response bodies, not only the status codes. The
   error payload changed shape for every refusal.

## Step 1: What `bustan doctor` Finds

```bash
bustan doctor path/to/your/app
```

It parses your files rather than importing them, because the code it is looking for is
exactly the code that no longer imports. It exits `1` on a finding, so it can gate a
migration in a pipeline. [reference/cli.md](../reference/cli.md#bustan-doctor) documents the command;
what follows is the migration behind each rule.

### The Four Renamed Packages

| 1.x | 2.0 |
| --- | --- |
| `bustan.core.*` | `bustan.kernel.*` |
| `bustan.platform.http.*` | `bustan.runtime.*` |
| `bustan.logger.*` | `bustan.observability.*` |
| `bustan.config.*` | `bustan.configuration.*` |

All four are internal, and they moved because 2.0 enforces a layering rule that the
old names contradicted; [explanation/layering.md](../explanation/layering.md) is where that rule is
written down. Renaming the import is the mechanical fix, and it is the wrong one if
the symbol is supported: prefer the same name from `bustan`, `bustan.errors` or
`bustan.testing`, which is a path that is now promised not to move.

A 1.x application reached inside the package because 1.x exported no other way to say
these things. Most of those reasons are gone:

```python
# 1.x
from bustan.core.ioc.tokens import InjectionToken
from bustan.logger.logger import LogLevel, Logger
from bustan.pipeline.guards import Guard

# 2.0
from bustan import Guard, InjectionToken, LogLevel, Logger
```

### `ThrottlerStorage`

1.x declared two synchronous methods; 2.0 declares one asynchronous method that counts
the request and reports the key's state in a single step.

```python
# 1.x
class RedisThrottlerStorage:
    def increment(self, key: str, ttl: int) -> int: ...
    def get_ttl(self, key: str) -> int: ...

# 2.0
from bustan import ThrottleState


class RedisThrottlerStorage:
    async def count_request(self, key: str, ttl: int, limit: int) -> ThrottleState: ...
```

Three obligations come with the new shape, and an implementation that ignores them
compiles and throttles wrongly:

- **Count and report atomically.** Where several processes share the store, two workers
  racing on one key will otherwise both be told they are within the limit.
- **Do not count a request the window has no room for.** A refused caller that is
  counted extends its own wait, so `Retry-After` grows every time it retries.
- **Report `reset_after` as whole seconds until the oldest request leaves the window**,
  never longer than the window itself.

`ThrottlerModule.for_root` also gained `storage`, `key_resolver`, `trusted_proxies` and
`max_keys`. A 1.x application that registered its own store by overriding the
`THROTTLER_STORAGE` token can now pass it directly:

```python
ThrottlerModule.for_root(ttl=60, limit=100, storage=RedisThrottlerStorage())
```

Read [how-to/harden-security.md](../how-to/harden-security.md#throttling) before setting
`trusted_proxies`, which is the one option on that list that can be set wrongly in a
way that helps an attacker.

### The Observability Protocols And The ASGI Body Error

Four of the doctor's ten rules name constructs that **did not exist in 1.1.0**:

| Rule | First shipped |
| --- | --- |
| `bustan.adapters.asgi.RequestBodyTooLarge` | `2.0.0-rc.2` |
| `MetricsSink.record_request` without `duration_seconds` | `2.0.0-rc.2` |
| `TraceSpan.finish` | `2.0.0-rc.2` |
| `RequestTracer.start_span` taking `labels` | `2.0.0-rc.2` |

They cannot fire on a genuine 1.x codebase. They are there for the other migration the
doctor serves: code written against a 2.0 release candidate. If you are coming from
1.x, expect these four to stay silent, and read
[how-to/observe-an-application.md](../how-to/observe-an-application.md) as new surface rather than as a change.

The same is true of `@RateLimit`: the decorator arrived in `2.0.0-rc.2`, so the window
rule finds nothing in a 1.x tree either. It matters the first time you write one.

### Five Of Ten Rules Apply To You

The doctor carries ten rules. Coming from 1.x, five of them can fire: the four renamed
packages, and the `ThrottlerStorage` pair. The other five name constructs 1.x never had.

That is a useful scan and it is not a migration. Everything below is the rest of it.

## Step 2: What Only You Can Find

Every item below was reproduced by taking one small 1.x application, running it on
`1.1.0`, running it on 2.0, and recording the difference. **None of them is reported by
`bustan doctor`**, because none leaves a trace in the text of a program.

### Two Lifecycle Hooks Were Renamed, And The Old Names Fail Silently

**This is the item to read twice.** Nothing raises, nothing warns, and the doctor cannot
see it. A 1.x application's startup and shutdown hooks simply stop being called.

| 1.x method | 2.0 method |
| --- | --- |
| `on_module_init` | `on_module_init`, unchanged |
| `on_app_startup` | **`on_application_bootstrap`** |
| `on_app_shutdown` | **`on_application_shutdown(signal)`** |
| `on_module_destroy` | `on_module_destroy`, unchanged |
| - | `before_application_shutdown(signal)`, new |

The protocol classes did not change name - `OnApplicationBootstrap` and
`OnApplicationShutdown` are what they always were - so nothing about your imports looks
wrong. Only the method the runner looks for moved. The same fixture, run on both:

```
1.1.0:  on_module_init -> ran, on_app_startup -> ran, on_app_shutdown -> ran, on_module_destroy -> ran
2.0:    on_module_init -> ran, on_application_bootstrap -> ran, on_application_shutdown -> ran, on_module_destroy -> ran
```

A class carrying the 1.x names on 2.0 has two dead methods and a startup and shutdown
that do nothing. Grep for both:

```bash
grep -rn "def on_app_startup\|def on_app_shutdown" .
```

**Both shutdown hooks take a `signal` parameter, and it is not optional.** A method
renamed without it fails at shutdown rather than being skipped:

```
bustan.kernel.errors.LifecycleError: Provider lifecycle hook Ledger.on_application_shutdown
failed: Ledger.on_application_shutdown() takes 1 positional argument but 2 were given
```

Declare it as `def on_application_shutdown(self, signal: str | None) -> None`. The value
is the name of the signal that stopped the process, or `None` when nothing signalled.

`before_application_shutdown` is new and has no 1.x equivalent. It runs before the
teardown begins, which is where a process withdraws itself from rotation; see
[how-to/deploy.md](../how-to/deploy.md#withdraw-from-rotation-before-you-stop-serving).

### A Request-Scoped Provider In A Default-Scoped Controller Now Refuses To Build

This is the change most likely to stop your application starting, and the one you are
least likely to predict, because 1.x accepted it.

```python
@Injectable(scope="request")
class RequestActor:
    def __init__(self, request: Request) -> None:
        self.actor = request.headers.get("x-actor", "anonymous")


@Controller("/orders")            # singleton by default
class OrderController:
    def __init__(self, orders: OrderService, actor: RequestActor) -> None: ...
```

On 1.x this application started and served. The controller was built once, so the
first caller's `RequestActor` was the one every later caller was served with: the
identity of whoever arrived first, returned to everybody. On 2.0 the container refuses
while the application is being built:

```
bustan.kernel.errors.ProviderResolutionError: OrderController.__init__ parameter
'actor' depends on request-scoped provider RequestActor, which can only be injected
into an owner that lives no longer than it does. A singleton-scoped owner outlives it
and would share one caller's instance with every later caller
```

The fix is to declare the owner request-scoped, so it lives no longer than what it
injects:

```python
@Controller("/orders", scope="request")
class OrderController: ...
```

[explanation/request-scope.md](../explanation/request-scope.md) covers the scope rules and
the cost of the request-scoped choice. **Audit every route that read per-caller state
off a singleton**: a build that now fails is the good case, and the applications worth
worrying about are the ones that were quietly serving one caller's data to another and
had no reason to notice.

### Every Error Body Changed Shape

1.x answered a refusal with `{"detail": "..."}`. 2.0 answers with RFC 9457 problem
details, on every refusal, from the edge to the handler and back:

```json
{
  "type": "https://bustan.dev/problems/forbidden",
  "title": "Forbidden",
  "status": 403,
  "detail": "Forbidden",
  "instance": "/orders",
  "code": "forbidden"
}
```

A client reading `body["detail"]` still finds a string, and it is no longer the same
string. A client reading anything else finds a payload it has never seen. Check every
consumer you own, and every test that asserts on an error body.

### A Refusal No Longer Names What Refused It

1.x returned the guard's dotted class path to the caller:

```
403 {"detail": "Guard myapp.guards.ApiKeyGuard blocked the request"}
```

2.0 returns `"Forbidden"` and writes the reason to the log instead, against the
request's correlation id. Nothing you can do to the response brings the old string
back, and you should not want it: the caller being refused is the one party those names
must not reach. If you were reading it in a test, read the log or the status instead.

### Body Fields Are Checked Against Their Declared Types

```python
@dataclass(frozen=True, slots=True)
class CreateOrder:
    sku: str
    quantity: int
```

`{"sku": "A-1", "quantity": "two"}` was `200` on 1.x, and the handler was handed a
`str` where its own annotation said `int`. On 2.0 it is `400`, with the offending field
named in the problem's `errors` array. A nested object now arrives as the type its
field declares rather than as a plain mapping.

Two things follow. Callers that were sending the wrong type and getting away with it
now fail, which is worth finding before your users do. And handlers that defensively
coerced their own arguments can stop.

### Every Application Serves Under Finite Request Limits

There were no limits in 1.x. In 2.0 an application that configures nothing still runs
under these:

| Limit | Default | A request over it |
| --- | --- | --- |
| `max_body_bytes` | 1 MiB | `413` |
| `max_upload_bytes` | 10 MiB | `413` |
| `max_upload_files` | 20 parts | `413` |
| `timeout_seconds` | 30 s | `504` |
| `sync_handler_threads` | 40 | queues |

A 2 MiB `POST` that 1.x answered `200` is answered `413` on 2.0 before the handler
runs. If your application legitimately accepts more, say so rather than discovering it
in production:

```python
from bustan import RequestLimits, create_app

app = create_app(AppModule, request_limits=RequestLimits(max_body_bytes=8 * 1024 * 1024))
```

`None` removes a bound for a deployment that has measured that it needs to, and is
never what you get by not choosing. [how-to/harden-security.md](../how-to/harden-security.md#request-limits)
explains what each bound is protecting and why raising one is a decision rather than a
default.

### `Application.close()` Stops The Server Now

In 1.1.0 `close()` was literally `pass`. It ran nothing, and it left a running server
serving; teardown only ever happened through the ASGI lifespan. On 2.0 it stops the
server the way a signal does, drains it, runs the teardown, and returns once the port is
released, so a caller may bind that port again or start the application afresh.

A rolling deploy that dropped in-flight requests will stop dropping them. A test that
called `close()` as a formality is now really tearing the application down, which is
usually what it wanted and occasionally a surprise. See
[how-to/deploy.md](../how-to/deploy.md#shutdown-and-draining) for the whole sequence.

### Log Records Are JSON

1.x wrote a formatted line:

```
[2026-09-08T20:22:32.381Z] [LOG] [Orders] creating order for A-1
```

2.0 writes one JSON object per record, through the standard library's `logging`, with
the request's correlation and trace ids attached:

```
{"timestamp":"2026-09-08T20:23:04.350Z","level":"LOG","context":"Orders","message":"creating order for A-1","correlation_id":"9246...","trace_id":"225e...","span_id":"adc0..."}
```

Anything that parsed the old line - a log-shipping regex, a dashboard, an alert - needs
rewriting against the fields. Configuring the `bustan` logger now configures the
framework's records and the framework's own internal records together, which it did not
before. [how-to/observe-an-application.md](../how-to/observe-an-application.md#logging) has the field list and the
redaction rules.

### `coerce_response` Returns A Neutral Response

A 1.x application that imported `bustan.platform.http.responses.coerce_response` got a
Starlette `JSONResponse` back. The renamed `bustan.runtime.responses.coerce_response`
returns a `bustan.contracts.HttpResponse`, because the runtime no longer knows what
transport is underneath it. Code that reached for the Starlette object's own API on the
result has to change; the doctor reports the rename and cannot report this.

Returning a Starlette response *from a handler* still works, and so does injecting
`starlette.requests.Request` into one. Both were checked.

### A 401 Where You Might Expect A 403

2.0 answers `401` with a `WWW-Authenticate` challenge when a request is refused for
want of an identity, and keeps `403` for a caller it has already identified. For a 1.x
application this is new capability rather than a change: 1.x had no way to express the
difference, and a plain guard that answers `False` still produces `403` exactly as it
did. It matters the first time you raise `AuthenticationRequiredError` or use `@Auth`.

### What Kept Working

Checked on the same fixture, on both versions, because "probably fine" is not something
a migration guide should say:

| 1.x construct | On 2.0 |
| --- | --- |
| `Guard.can_activate(self, context)` | works, unchanged |
| `Pipe.transform(self, value, context)` | works, unchanged |
| `Interceptor.intercept(self, context, call_next)` and `await call_next()` | works; the parameter is now a `CallHandler`, and it is still callable |
| `Middleware.use(self, request, call_next)` | works, unchanged |
| `ExceptionFilter.catch(self, exc, context)` and `exception_types` | works, unchanged |
| Injecting `starlette.requests.Request` into a provider or handler | works |
| Returning a Starlette response from a handler | works |
| Writing to `request.state` | works |
| `RequestContext` and `ParameterContext` as annotations | work; they are shims over `ExecutionContext` |

Two of those have a caveat rather than an exception. A middleware's `request` is a
`bustan.contracts.HttpRequest` now, not a Starlette `Request`: `request.url.path` and
`request.headers` read the same, and anything reaching for Starlette's own API needs
`request.native_request`. And `ExecutionContext` is the supported name for what
`RequestContext` shims, so move the annotation when you touch the file.

## A Worked Migration

The application below is the fixture this guide was validated against. It ran on
`1.1.0` and it is what a 1.x application looked like: internal imports, a throttler
store, a guard, and a request-scoped provider injected into a default-scoped
controller.

```python
from bustan import ConfigModule, Controller, Get, Injectable, Module, Post, ThrottlerModule
from bustan.config.config_service import ConfigService
from bustan.core.ioc.tokens import InjectionToken
from bustan.logger.logger import LogLevel, Logger
from bustan.pipeline.context import RequestContext
from bustan.pipeline.guards import Guard
from bustan.platform.http.responses import coerce_response


class RedisThrottlerStorage:
    def increment(self, key: str, ttl: int) -> int: ...
    def get_ttl(self, key: str) -> int: ...


@Injectable(scope="request")
class RequestActor:
    def __init__(self, request: Request) -> None:
        self.actor = request.headers.get("x-actor", "anonymous")


@Controller("/orders")
class OrderController:
    def __init__(self, orders: OrderService, actor: RequestActor) -> None: ...
```

`bustan doctor` reported six findings against it: the four renamed packages, and
`increment` and `get_ttl`. Applying all six, and nothing else, left an application that
the doctor called clean and that **still would not start**, because of the
request-scoped controller. That is the whole argument of this guide in one experiment.

The finished migration was:

```python
from bustan import ConfigModule, ConfigService, Controller, ExecutionContext, Get, Guard
from bustan import InjectionToken, LogLevel, Logger, Module, Post, ThrottleState
from bustan import ThrottlerModule
from bustan.runtime.responses import coerce_response


class RedisThrottlerStorage:
    async def count_request(self, key: str, ttl: int, limit: int) -> ThrottleState: ...


class ApiKeyGuard(Guard):
    async def can_activate(self, context: ExecutionContext) -> bool: ...


@Controller("/orders", scope="request")
class OrderController:
    def __init__(self, orders: OrderService, actor: RequestActor) -> None: ...
```

Six of the seven edits are import lines. The seventh is the one nothing told us about.

Two details in that diff are worth taking rather than translating literally. `Guard`,
`InjectionToken`, `Logger`, `LogLevel` and `ConfigService` were all internal imports in
1.x and are all supported exports in 2.0, so the migration is to `bustan` rather than
to the renamed internal path. And `RequestContext` survives as a shim over
`ExecutionContext`, so a 1.x guard's annotation keeps working; `ExecutionContext` is
the supported name and the one to move to.

## When You Are Done

- `bustan doctor` exits `0` over your whole tree.
- Every item in [Step 2](#step-2-what-only-you-can-find) has been checked by reading
  your own code, not by running a tool.
- `grep -rn "def on_app_startup\|def on_app_shutdown" .` finds nothing, and every
  `on_application_shutdown` and `before_application_shutdown` takes a `signal`
  parameter.
- Your tests assert on the problem-details shape rather than on `{"detail": ...}`.
- No controller injects a request-scoped provider without being request-scoped itself.
- Your body-size and timeout limits are the ones you chose, or you have confirmed the
  defaults fit.
- Your throttler has a shared store if you run more than one worker
  ([how-to/harden-security.md](../how-to/harden-security.md#throttling)).
- Your readiness probe is wired to your scheduler
  ([how-to/deploy.md](../how-to/deploy.md#health-and-readiness)).

## Where To Go Next

- [reference/cli.md](../reference/cli.md) - the whole of `bustan doctor`, and the other four commands.
- [explanation/layering.md](../explanation/layering.md) - why the packages moved.
- [how-to/observe-an-application.md](../how-to/observe-an-application.md) - logging, correlation, metrics and tracing.
- [how-to/harden-security.md](../how-to/harden-security.md) - limits, throttling, refusals.
- [how-to/deploy.md](../how-to/deploy.md) - serving, probes, draining, workers.
- [CHANGELOG.md](../../CHANGELOG.md) - every change, release by release, with the issue
  each one closed.
