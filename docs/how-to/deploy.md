# Deployment

How to install, serve, probe, scale and stop a `Bustan` application. It assumes the
application already runs locally; [tutorials/first-app.md](../tutorials/first-app.md) is where that starts.

## Install

Bustan requires Python 3.13 or newer, and uv is the only supported package manager.

`bustan` on its own is not a web server, and installing it does not install one:

```bash
uv add bustan               # the kernel: injection, modules, lifecycle
uv add "bustan[starlette]"  # plus the adapter this package ships
```

The `starlette` extra brings `starlette`, `uvicorn` and `python-multipart`. That last
one is not optional within the extra: Starlette refuses every form body, urlencoded as
well as multipart, unless it is installed, so without it a route binding `UploadedFile`
answers `500` on this adapter and `200` on the raw ASGI one.

`scripts/package_smoke_check.py` builds two environments from the wheel and proves both
halves of that in CI: that a plain install pulls in no web server and that the kernel
imports without one, and that a scaffolded project runs under the extra.

## Serving

Three ways, and they differ in who owns the process.

### The Application Owns The Process

```python
import asyncio

from bustan import create_app

from .app_module import AppModule


async def bootstrap(reload: bool = False) -> None:
    app = create_app(AppModule)
    await app.listen(port=3000, host="0.0.0.0", drain_timeout=25.0)


def main() -> None:
    asyncio.run(bootstrap())
```

This is what `bustan init` scaffolds, behind the project's `start` and `dev` scripts.
`listen` runs the server until it is signalled or stopped, and handles `SIGINT` and
`SIGTERM` itself. It is the only one of the three that gives you the drain sequence
described below.

### An External ASGI Server Owns The Process

`Application` is an ASGI callable, so any ASGI server can serve it:

```bash
uvicorn myapp.main:app --host 0.0.0.0 --port 3000
```

Startup and shutdown still run, because they run through the ASGI lifespan the
application was built with. What you give up is `drain_timeout` and the signal name
your teardown hooks would otherwise be handed: those come from `listen`, and under an
external server the server's own graceful-shutdown settings are what apply.

### No HTTP At All

```python
from bustan import create_app_context

context = create_app_context(AppModule)
await context.init()
worker = context.get(QueueWorker)
```

`create_app_context()` gives injection and lifecycle with no server: the right shape for
a queue consumer, a scheduled job or a management command that has to share the
application's providers. `ApplicationContext` supports `get()`, `resolve()`, `init()`
and `close()` and nothing HTTP. See
[reference/adapters.md](configure-the-platform.md#non-http-bootstrapping).

## Choosing An Adapter

Left alone, the application serves through the Starlette adapter. The second adapter
ships in the same package and needs no third-party library at all:

```python
from bustan import create_app
from bustan.adapters.asgi import AsgiAdapter

app = create_app(AppModule, adapter=lambda runtime: AsgiAdapter(lifespan=runtime.lifespan))
```

Pass a callable rather than a built adapter when you want the framework to hand it the
lifespan and the debug flag it was assembled with. Both adapters are held to the same
answers by `scripts/conformance_matrix.py`, which runs in CI over every case and fails
when the two disagree.

Both currently declare the same capabilities - raw bodies and streaming responses yes,
host routing and WebSocket upgrade no - so the choice between them is about dependencies
rather than features. That can change, and the framework checks a route's requirements
against the adapter's capabilities while compiling, so a route an adapter cannot serve
is refused at startup rather than at the first request that needs it. Read
`app.get_http_adapter().capabilities` rather than assuming.

## Health And Readiness

```python
from bustan import HealthModule


@Module(imports=[HealthModule.for_root(check_timeout=2.0)], ...)
class AppModule:
    pass
```

| Probe | Route | Wire it to |
| --- | --- | --- |
| Liveness | `GET /health/live` | the restart decision |
| Readiness | `GET /health/ready` | the routing decision |

Both answer `200` when up and `503` when down, with `cache-control: no-store`, so
nothing between the process and the reader can answer the next probe out of a cache.

A Kubernetes deployment wires them as its liveness and readiness probes. Give the
readiness probe a short period and a low failure threshold, because it is the one that
takes a pod out of rotation and back; give liveness a long one, because its failure kills
the process.

Keep `check_timeout` below the interval the probe is read on. Indicators are checked
together, so it bounds the whole probe however many are registered.

**The two probes are not interchangeable**, and putting a dependency on the wrong one
turns an outage in something else into a restart loop.
[how-to/observe-an-application.md](../how-to/observe-an-application.md#health-and-readiness) has the rule and the
registration example.

**Neither probe is authenticated, and neither is exempt from a global guard you
install.** An application that authenticates every request must exclude these two routes
itself, or its probes fail permanently.

## Shutdown And Draining

`listen()` gives the whole sequence. A `SIGINT` or `SIGTERM` arriving while it is
serving:

1. Closes the gate, so new requests are refused.
2. Waits up to `drain_timeout` seconds for the requests already in flight. A request
   that outlasts the window is cancelled rather than allowed to hold the process open.
3. Runs the shutdown hooks, telling them which signal arrived.
4. Releases the listening port.

`drain_timeout` defaults to 10 seconds on the Starlette adapter. Set it above your
slowest ordinary request and below whatever your orchestrator's termination grace period
is, or the orchestrator kills the process partway through step 2.

`await app.close()` does the same thing without a signal: it stops a running server,
drains it, runs the teardown, and returns once the port is released, so a caller may bind
that port again.

### Withdraw From Rotation Before You Stop Serving

Readiness has to go false while the process is still serving normally, so traffic is
withdrawn from it by whatever routes traffic before it stops being able to accept any.
The teardown hook sets the draining edge as a backstop, but by then the process has
already stopped serving. A shutdown sequence that wants the gap closed says so earlier:

```python
from bustan import Injectable, ReadinessState


@Injectable
class Drainer:
    def __init__(self, readiness: ReadinessState) -> None:
        self._readiness = readiness

    def handle_termination(self) -> None:
        self._readiness.begin_drain()
```

Call `begin_drain()` first, before the teardown hooks run and before any request is
refused, and only then wait for in-flight requests to finish. Draining only as part of
teardown takes the process out of rotation once it has already stopped serving, which is
the outage this prevents.

### Teardown Hooks

`before_application_shutdown`, `on_application_shutdown` and `on_module_destroy` run in
that order. Every stage runs to completion even when a hook fails, so one buggy
component cannot leak every other component's resources; the failures are collected and
raised together afterwards.

The two shutdown hooks take a `signal` argument. It is the signal's name - `SIGTERM`,
`SIGINT` - when the stop came from a signal that `listen()` handled, and `None`
otherwise: an `await app.close()`, or a lifespan shutdown under an external server.
Write a hook that behaves correctly for both, because the same hook runs in a test and
in a deploy.

If your application came from 1.x, check the method names before you deploy: 1.x called
these `on_app_startup` and `on_app_shutdown`, and a class still carrying those names has
a startup and a shutdown that silently do nothing. See
[how-to/migrate-from-1x.md](../how-to/migrate-from-1x.md#two-lifecycle-hooks-were-renamed-and-the-old-names-fail-silently).

[reference/lifecycle.md](../reference/lifecycle.md) has the full ordering.

## Running More Than One Worker

Each worker is its own process with its own container, so anything the framework holds
in memory is per-process. Two of those matter in production:

- **The throttler.** The default store counts each worker separately, so N workers allow
  N times the configured limit. Pass a `storage` implementation every worker can see.
  This is the most common way a rate limit turns out not to be one; see
  [how-to/harden-security.md](../how-to/harden-security.md#throttling).
- **Anything a singleton provider caches.** A cache, a counter, an in-memory session
  store: each worker has its own, and a caller striped across workers sees whichever one
  it lands on.

`sync_handler_threads` bounds each worker independently too, so a four-worker deployment
under the default runs up to 160 synchronous handlers at once.

## Behind A Proxy

If anything sits between your callers and the application - a load balancer, an ingress,
a CDN - the address the application sees is the proxy's. Two consequences:

- **Tell the throttler which peers may name the caller.** `trusted_proxies` is empty by
  default, which ignores forwarding headers entirely and counts every request under the
  address it arrived from. Set it to the peers you actually accept connections from and
  nothing wider: any peer in that list can claim to be any caller.
- **Terminate TLS there.** The framework does not. Nor does it write any security
  response header; add those at the proxy or in a middleware of your own.

## Configuration

`ConfigModule.for_root()` resolves configuration by overlaying the process environment
onto the environment files it was given, so a deployment supplies values as environment
variables in the ordinary way.

```bash
bustan config myapp.app_module:AppModule
```

prints what the application actually resolved, with credential-looking keys withheld.
Two limits before you paste that anywhere: redaction reads the name of a key and never
its value, and the report covers the whole process environment because that is what
configuration is overlaid from. [reference/cli.md](../reference/cli.md#bustan-config) says the rest.

## Gating A Release

The CLI answers questions a deployment pipeline can act on. `doctor` exits `1` when it
has findings, so it can be a step that fails the build; the route commands always exit
`0` and answer in their output, so a pipeline that gates on the route surface compares
that output itself:

| Command | Question |
| --- | --- |
| `bustan doctor` | Does this codebase still contain constructs 2.0 changed? |
| `bustan routes snapshot` / `bustan routes diff` | What changed in the served route surface since the last release? |

Commit the route snapshot and diff each candidate against it, and an unintended route
removal is caught before it reaches a caller rather than after.
[reference/cli.md](../reference/cli.md#bustan-routes) documents both.

## Before You Ship

- The `starlette` extra is installed if you serve on the Starlette adapter.
- `drain_timeout` is above your slowest request and below the termination grace period.
- Readiness is wired to routing, liveness to restarts, and neither is behind a guard
  that refuses them.
- Something calls `begin_drain()` on the termination signal.
- Every teardown hook has been read, especially if this application came from 1.x.
- The throttler has a shared store if you run more than one worker.
- `trusted_proxies` names your load balancer and nothing wider.
- TLS and security response headers are handled in front of the application.
- Request limits fit what your routes actually accept
  ([how-to/harden-security.md](../how-to/harden-security.md#request-limits)).

## Where To Go Next

- [how-to/observe-an-application.md](../how-to/observe-an-application.md) - logs, correlation, metrics, traces, probes.
- [how-to/harden-security.md](../how-to/harden-security.md) - limits, throttling, refusals.
- [reference/adapters.md](../reference/adapters.md) - the adapter surface.
- [reference/lifecycle.md](../reference/lifecycle.md) - startup and shutdown ordering.
- [how-to/cut-a-release.md](../how-to/cut-a-release.md) - releasing the framework itself.
