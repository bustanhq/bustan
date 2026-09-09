# Observability

What a `Bustan` application emits about itself, and how to attach your own backends to
it. Four things, and they are separate on purpose: **logs** say what happened,
**correlation** joins one request's records together and to the caller's trace,
**metrics** say what every request cost, and **traces** say what one request was worth
keeping.

An application that configures nothing still logs structured records and still
correlates them. Metrics and traces need a backend, because the framework does not
choose one for you.

## Logging

`Logger` writes one JSON object per record through the standard library's `logging`,
on the logger named `bustan`.

```python
from bustan import LogLevel, Logger

logger = Logger("Orders")
logger.log("order accepted")
logger.record(LogLevel.WARN, "retrying payment", fields={"attempt": 2, "order_id": 41})
```

```
{"timestamp":"2026-09-08T20:23:04.350Z","level":"LOG","context":"Orders","message":"order accepted","correlation_id":"9246...","trace_id":"225e...","span_id":"adc0..."}
```

| Field | Always present | What it is |
| --- | --- | --- |
| `timestamp` | yes | UTC, millisecond precision, `Z`-suffixed. |
| `level` | yes | `VERBOSE`, `DEBUG`, `LOG`, `WARN` or `ERROR`. |
| `context` | yes | The label the logger was built with, or the one passed to the call. |
| `message` | yes | The message, encoded. |
| `correlation_id`, `trace_id`, `span_id` | only inside a served request | The identity of the request in flight. |
| your own fields | when passed | Whatever `record(..., fields=...)` carried, redacted. |

### Why It Is JSON

Because the previous format was an f-string printed to standard output. A message
containing a newline arrived at the reader as two lines, the second of which was a
well-formed record of the writer's choosing, with whatever context and timestamp it
wanted. Encoding escapes the separator that made that possible, so a message can no
longer end one record and begin another however it is written. `ensure_ascii` is on, so
every byte written is ASCII and a newline anywhere in the record - message, field name
or field value - is written as the two characters that mean one.

### Structured Fields Go Through `record`

The five level methods take a message and a context and nothing else. Structured fields
go through `record`, deliberately: those five are overridden by applications and by
this framework's own tests, and adding a parameter to a method someone else has already
overridden turns their subclass into one that no longer satisfies its base class.

A caller's field never replaces a framework key. A record that arrives with a `level`
or a `context` of its own is describing something the caller cares about, not the
record.

### Redaction

Field values are withheld by name, at any depth, before anything is written. Matching
folds case and nothing else. The default key set covers the names a credential is
conventionally carried under - `authorization`, `password`, `token`, `api_key`,
`set-cookie` and the rest - and an application replaces the whole set:

```python
Logger.set_redacted_keys({"authorization", "password", "x-tenant-secret"})
```

Two limits are worth knowing before you rely on it:

- **A credential inside a value is not withheld.** Redaction reads the name of a key,
  never its value.
- **The walk is depth-bounded.** Past eight levels a value is rendered rather than
  descended into, which terminates on a self-referential structure and keeps an
  accidentally deep one from costing a request its stack.

### Configuring It

The logger name is the package name, so configuring `bustan` configures the framework's
own records and the records its execution engine, filters and guards emit, in one
place:

```python
import logging

logging.getLogger("bustan").setLevel(logging.INFO)
```

`Logger.set_global_level(LogLevel.DEBUG)` sets the framework level records are written
at. `LoggerService` is the same logger as an injectable provider, for a service that
would rather be handed one than build one.

`Logger.scoped_override(target)` redirects records for the context that installed it
and for nothing else, which is what a test uses; it does not redirect another request's.

## Correlation

Every request is named before anything runs for it, and the name is bound for as long as
the request is. Every log record and every span the request produces carries it -
including the ones a middleware writes before the route is reached and the ones a
failure writes after it is left.

**Incoming headers, in the order they are consulted:**

| Header | What it does |
| --- | --- |
| `x-correlation-id` | Names this request. Honoured when it is 1 to 128 printable ASCII characters; anything else is replaced by a generated id rather than repaired. |
| `x-request-id` | The same, consulted second. Proxies and other frameworks commonly set it. |
| `traceparent` | W3C Trace Context, version `00`. A valid value joins this request to the caller's trace and carries the caller's sampling decision forward. |

A `traceparent` the specification refuses - version `ff`, an all-zero trace or span id,
a malformed value - starts a new trace here rather than propagating something that
cannot be true.

**There is no outgoing correlation header.** The framework binds the id, writes it into
every record, and puts it on the span; it does not add it to the response. If your
clients need to quote it back at you, write it from an interceptor or a middleware of
your own.

The correlation helpers themselves live in `bustan.observability.correlation` and are
not part of the supported surface, so read the ids off your log records rather than
importing them. See [reference/stability.md](../reference/stability.md).

## Metrics And Traces

Both are attached at `create_app`, through one object:

```python
from bustan import ObservabilityHooks, create_app

app = create_app(
    AppModule,
    observability=ObservabilityHooks(metrics=my_sink, tracer=my_tracer, sample_ratio=0.05),
)
```

The hooks belong to that application rather than to the process, so a second
application in the same process can report somewhere else. Left out, requests are still
measured and still correlated; there is simply nothing listening.

### `MetricsSink`

One call per finished request, whatever it was answered with.

```python
from collections.abc import Mapping


class PrometheusSink:
    def record_request(self, *, labels: Mapping[str, str], duration_seconds: float) -> None:
        REQUESTS.labels(**labels).inc()
        LATENCY.labels(**labels).observe(duration_seconds)
```

| Label | Example |
| --- | --- |
| `controller` | `OrderController` |
| `route` | `POST /orders` |
| `operation` | `OrderController.create` |
| `version` | `neutral` |
| `status` | `413` |

The duration is elapsed time from the moment the request was admitted, taken from a
monotonic clock. It covers everything the request paid for - the guards, provider
resolution, reading the body, the handler, and rendering the answer - not merely the
handler. A request that was refused is measured too, which is the point: the refusals
are where the interesting latency usually is.

A sink written without `duration_seconds` is still called, with the labels alone. The
request is counted and never timed. `bustan doctor` reports such a sink;
[how-to/migrate-from-1x.md](../how-to/migrate-from-1x.md) has the edit.

### `RequestTracer` And `TraceSpan`

The span model is OpenTelemetry's: set attributes while the request runs, record the
exception if there was one, set the status once, end once.

```python
from collections.abc import Mapping

from bustan import SpanContext, SpanKind, SpanStatus, TraceSpan


class OtelTracer:
    def start_span(
        self,
        name: str,
        *,
        kind: SpanKind,
        attributes: Mapping[str, str],
        context: SpanContext,
    ) -> TraceSpan:
        ...
```

`context` names the trace the span belongs to and the caller's span when the request
arrived inside one, so a span this process starts continues the caller's trace rather
than beginning one beside it.

The runtime starts one `SERVER` span per sampled request, named after the route's
`operation` label, with the route labels and the correlation id as attributes. On
completion it sets `http.status_code` and `duration_seconds`, records the exception if
there was one, sets the status, and ends the span. The status follows OpenTelemetry's
convention rather than the intuitive one: a 4xx leaves the span `UNSET`, because a
refused request is the server working correctly, and `ERROR` is reserved for a 5xx or
an exception.

### Sampling

`sample_ratio` is a head decision, made once when the request starts and true for the
whole trace. A caller that already sampled the request is honoured; a request that
arrived without a decision gets one derived from its trace id and the ratio.

**Sampling decides spans, not metrics.** An unsampled request is still counted and still
timed, because the metric is what every request costs and the span is what one request
is worth keeping.

## Health And Readiness

`HealthModule.for_root()` registers two routes and exports the service and the
readiness state.

| Route | Question | Status |
| --- | --- | --- |
| `GET /health/live` | Is this process alive? | `200` up, `503` down |
| `GET /health/ready` | Should this process be sent traffic? | `200` up, `503` down |

```json
{
  "status": "down",
  "checks": {
    "lifecycle": {"status": "down", "detail": "startup has not completed"},
    "database": {"status": "up", "detail": null}
  }
}
```

The shape is exactly two levels deep and has no optional keys, so a reader never has to
tell a missing key from an absent detail. It carries no timing, no version and no host
name: those identify the process to anything that can reach the probe, and none of them
is needed to decide whether to route to it.

### The Two Probes Answer Different Questions

**Liveness starts with nothing registered against it and should usually stay that way.**
The only honest evidence that a process is alive is that it answered. A failing
dependency is not a reason to kill and restart a process that is working, and
registering one here turns an outage in something else into a restart loop that cannot
fix it. Register a liveness indicator only for a fault the process has detected in
itself and cannot clear without being restarted.

**Readiness is where the dependencies go.** It always begins with the built-in
`lifecycle` check, which is down before startup finishes and down again from the moment
the process is asked to stop. A readiness indicator going down takes one pod out of
rotation, which is recoverable.

### Registering An Indicator

```python
from bustan import HealthIndicatorResult, HealthService, Injectable


@Injectable
class DatabaseIndicator:
    name = "database"

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    async def check(self) -> HealthIndicatorResult:
        if await self._pool.ping():
            return HealthIndicatorResult.up()
        return HealthIndicatorResult.down("the primary is not answering")


@Injectable
class HealthWiring:
    def __init__(self, health: HealthService, database: DatabaseIndicator) -> None:
        self._health = health
        self._database = database

    def on_module_init(self) -> None:
        self._health.register_readiness(self._database)
```

Register from a module initialization hook. That stage runs before any hook can report
the application started, so an indicator registered there is already being consulted the
first time readiness can be true.

**A `detail` crosses a trust boundary.** Anything that can reach the probe reads it, so
say what is wrong in your own words and never put a host name, a connection string, a
credential or a dependency's exception message in it.

### An Indicator Cannot Take A Probe Down

One that raises, one that does not answer within the check timeout, and one that answers
with something that is not a result are each recorded as a down check under their own
name, and the probe still reports on every other indicator. The failure is logged in
full; what reaches the caller names only the kind of failure.

Indicators are checked together rather than in sequence, so one slow dependency does not
delay the answer about the others. `check_timeout` bounds the whole probe however many
are registered; keep it below the interval the probe is read on.

```python
HealthModule.for_root(check_timeout=2.0)
```

### What The Probes Are And Are Not Exempt From

Both routes skip throttling, because a rate-limited probe reports a process that is
serving perfectly well as failed, and something then restarts it or takes it out of
rotation for the load somebody else put on it.

**They are not exempt from a guard you install globally.** An application that
authenticates every request must exclude these two routes itself, because only it knows
what its own guards read. A probe that is answered with a rejection is a probe that
fails permanently.

## Where To Go Next

- [how-to/deploy.md](../how-to/deploy.md) - wiring the probes to a scheduler, and the drain
  sequence readiness is part of.
- [how-to/harden-security.md](../how-to/harden-security.md) - what a refusal is allowed to say,
  and what never reaches a log.
- [how-to/run-benchmarks.md](../how-to/run-benchmarks.md) - what the framework itself costs.
- [how-to/migrate-from-1x.md](../how-to/migrate-from-1x.md) - the shape these protocols had before,
  and the edit to each.
