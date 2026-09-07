# Bustan runtime roadmap

Bustan is an application architecture runtime for Python. It owns composition and
lifetime: modules as real boundaries, constructor injection, scoped providers, and one
pipeline around every invocation, whether that invocation is an HTTP request, a
consumed event, a queued job, or a socket message. Tasks and streams are scoped by the
same container that resolves dependencies, so nothing outlives what it depends on.
Adapters keep the platform underneath visible, and Starlette is the first one.

That is the product. This document is the plan for making every clause of it true, and
the record of which clauses are true today.

## How to use this document

[BUSTAN_2_0_BACKLOG.md](BUSTAN_2_0_BACKLOG.md) is the authority until `2.0.0` ships.
Nothing here reopens a ticket in it, changes a wave, or competes for an agent. This
document takes over at the `2.0.0` tag, with one exception: the section
`## Decisions to take inside the 2.0 programme` names changes to tickets that are still
open, because each is a sentence to write now and a migration to run later.

**Only the next release is planned at ticket level.** The 2.0 programme could be
written out seven days ahead because an audit had already found the defects and the
tickets were transcriptions of evidence. Nothing of the sort exists for a transport
that has not been written yet. A release here therefore states its theme, the contracts
it adds, the proof that those contracts hold, and its risks; it becomes ticket-shaped,
with `Owns` lists and acceptance criteria, only once the release before it has merged.
A plan that pretends to more precision than that is a plan that gets followed off a
cliff.

**Counts.** The backlog states no count a reader could measure, because a count in a
shared instruction goes stale silently. The rule is kept here with one carve-out:
`## Where the code stands` is a measurement, taken at commit `f3674d7`, and every
number in it is stamped with that commit. That makes it history rather than a claim
about the tree you have, and history does not decay. Everywhere else in this document,
measure it yourself.

**Recommendations are marked.** Where this roadmap chooses between defensible options
it says so and gives the reason, and the open ones are collected under
`## Open decisions`. A recommendation is not a decision until it is taken.

## The thesis

The product statement makes four claims. Each one is either true or not claimed; there
is no third state in which it appears in the README and fails at runtime. That third
state is what the container audit and its three follow-up surveys spent this year
cataloguing, and what the 2.0 programme exists to end.

1. **One composition and injection model across every entrypoint**, borrowed from
   NestJS, expressed in Python's typing and async model.
2. **Guards, pipes, interceptors, and filters that behave the same** whether the
   trigger is a request, a job, or an event.
3. **Task and stream lifetimes owned by the runtime** rather than the caller.
4. **Transports as adapters**, with direct access to the one you are on.

Under all four is a single change of noun.

> **The unit of work is an invocation, not a request.**

An HTTP request is one kind of invocation. A consumed event, a queued job, a socket
message, and a scheduled tick are others. Everything the framework owns for the
duration of one unit of work — the scope its providers are cached in, the pipeline that
runs around it, the tasks it spawns, the deadline it runs under, the identity it is
logged against, and the disposition its result is turned into — is owned per invocation
and is spelled the same way for every kind.

Three consequences run through every release below, and each one is a place the current
code says `request` and will have to say `invocation`:

- **A scope is opened by the runtime, not by a transport.** Today the request-scope
  cache lives on the transport's own request object. It has to live in a record the
  runtime holds, or a kind with no request object has no scope.
- **A failure has an outcome, not a status code.** Today an exception filter returns an
  HTTP response. A guard that refuses a job cannot return 403; it produces a refusal,
  and the entrypoint that received the job decides whether that means a dead-letter, a
  discard, or a retry.
- **A scope closes when its work is finished, not when its function returns.** Today a
  streamed body is written after the scope that produced it has been popped. Owning
  lifetime means the runtime, not the transport, decides when the last thing depending
  on a scope is done with it.

## Where the code stands

Measured at commit `f3674d7`, `2.0.0rc3`, with wave 4 of the 2.0 programme in flight.

### What already carries the thesis

More of the foundation is in place than the four claims suggest, and the roadmap is
mostly a matter of widening what exists rather than inventing it.

- **The scope algebra is general and static.** `src/bustan/kernel/ioc/planning/scopes.py`
  computes an effective scope per binding from the whole dependency chain, before
  anything is built, and refuses every edge where an owner would hold state shorter-lived
  than itself. It is written over an ordering of cache widths, not over HTTP. Adding a
  scope is an entry in a table plus its rules; the enforcement comes free.
- **The pipeline stages are already neutral in their signatures.** `Guard`, `Pipe`,
  `Interceptor` and `ExceptionFilter` take an `ExecutionContext` and nothing else. The
  HTTP assumptions are in what the context can be built from and in what a filter is
  allowed to return, not in the stages themselves.
- **There is a contracts package with a rule that nothing may import into it**
  (`src/bustan/contracts/`), a narrowed adapter port, a second HTTP adapter written
  against the ASGI specification and the standard library alone, a conformance matrix
  that holds both adapters to the same answers, and a layering table that names which
  packages may see a web server. That machinery is exactly what a second *kind* of
  entrypoint needs; it was built for a second implementation of one kind.
- **Lifecycle is owned by the framework**, through `LifecycleManager` and a lifespan the
  adapter drives, with module and provider hooks, ordered startup and shutdown, and a
  graceful-shutdown path landed in wave 4.
- **The public surface is small and pinned.** `bustan.__all__` is asserted as an ordered
  tuple and the API reference is generated and compared byte for byte, so a vocabulary
  change is a deliberate three-file edit rather than a drift.

### What is shaped like HTTP

Each of these is a place the thesis is currently aspiration, with the file that decides
it. None is a defect against the 2.0 backlog, which scoped itself to one kind of
entrypoint on purpose.

- **`ArgumentsHost.get_type()` is annotated `Literal["http"]`** and `ExecutionContext`
  has exactly one factory, `create_http` (`src/bustan/pipeline/context.py`). The NestJS
  shape that exists to let a filter ask what kind of trigger it is looking at can only
  answer one way.
- **The scope manager is keyed on the transport's request.** `push_request`,
  `get_request_cache` and `get_request_controller_cache` all take an `HttpRequest`, and
  the per-request instance tables are stored as attributes on `request.state`
  (`src/bustan/kernel/ioc/scopes.py`). A kind with no request object cannot open a
  scope, and the cache's lifetime is the transport's object's lifetime.
- **The scope algebra names HTTP types as the request-derived tokens**
  (`HttpRequest`, `HttpResponse`, `REQUEST`, `RESPONSE`), so "state the server owns for
  one unit of work" is currently spelled in HTTP nouns.
- **The adapter port is an HTTP port.** `AbstractHttpAdapter` converts a native request
  to `HttpRequest` and a result to a native response; `AdapterRoute` addresses work by
  `path` and `methods` (`src/bustan/contracts/adapter.py`). There is no shape in which
  a subscription, a queue, or a channel is addressable.
- **Parameter binding sources are HTTP sources** (`src/bustan/runtime/params.py`):
  `Body`, `Query`, `Param`, `Header`, `Cookies`, `UploadedFile`. There is no neutral
  payload or metadata marker for a message.
- **Failure rendering is HTTP rendering.** `ExceptionFilter.catch` returns
  `HttpResponse | None`, `execute_http_route` produces an `HttpExecutionResult`, and the
  one error contract landed in wave 4 is a problem-details document with a status code.
  A refusal has no spelling that is not a status.
- **The conformance suite certifies HTTP adapters.**
  `evaluate_adapter_conformance(adapter: AbstractHttpAdapter)` is the entry point, and
  every scenario is a request and a response.
- **`Application.enable_cors()` imports `starlette.middleware.cors` directly**
  (`src/bustan/app/application.py`), so a public method of the public application object
  works on one of the two adapters that ship. It is one of the nine violations
  `scripts/check_layering.py` reports while the check is still advisory.

### What is not there at all

- **Nothing owns a task.** Outside two adapter-internal `asyncio.create_task` calls,
  the package creates no tasks and opens no task group. There is no way for an
  application to spawn work that the runtime will join, cancel with its invocation, or
  drain at shutdown, and no rule that says what happens to work it spawns itself.
- **Nothing tears an invocation scope down.** `clear_request_state` drops the instance
  tables; no `close`, `__aexit__` or destroy hook is called on anything the scope built.
  The container has no notion of a disposable provider — no generator or context-manager
  provider form exists — so a request-scoped provider that opens a connection has no
  supported way to close it. The static check refuses to let a long-lived owner hold
  short-lived state; the runtime does not yet finish the sentence by disposing of the
  short-lived state when its scope ends.
- **A streamed response outlives its scope.** `execute_http_route` pops the request
  scope in a `finally` block and returns the response; when that response is an
  `HttpStreamResponse` wrapping an async iterator, the adapter drains the iterator
  afterwards. The generator therefore runs after the scope that owns the providers it
  closes over has been popped. This is the clearest existing instance of the caller
  owning a lifetime the runtime claims.
- **There is no socket path.** `AdapterCapabilities.supports_websocket_upgrade` exists
  and is `False` on both shipped adapters.
- **There is no scheduling, no job, and no event entrypoint**, and no vocabulary for
  one.

### What the 2.0 programme still owes

Wave 4 is in flight against `2.0.0-rc.4`; waves 5 and 6 are open. `2.0.0` remains the
first production-ready release and this roadmap does not move it. What follows starts
after it, and the roadmap's first job is to not make that finish line further away.

## Decisions to take inside the 2.0 programme

Six tickets are still open, and each contains a choice that costs one sentence now and
a migration later. None of these adds scope to a ticket; each replaces an HTTP-shaped
answer with the neutral one. They are listed with the open issue that carries them.

**1. Root the exception hierarchy in failures, not statuses (T-401, issue #149).**
The ticket adds a usable exception hierarchy so an application can return a 404 through
the framework's own error model. Make the base of that hierarchy name what went wrong —
not found, not permitted, invalid input, conflict, unavailable, timed out — and make the
HTTP status a mapping applied where the response is rendered. A hierarchy rooted in
`HttpException(status_code)` has to be re-rooted before any other kind can raise from
a service, and a service is exactly the code that gets shared between an HTTP handler
and a job. Cost now: naming. Cost later: every application's exception classes.

**2. Make health and readiness a runtime concern with an HTTP surface (T-402, issue
#150).** Readiness eventually has to answer for a consumer that has not subscribed yet,
not only for a server that has not bound a port. Register checks against the
application, and let the HTTP entrypoint expose them; do not define readiness as a
route.

**3. Give observability invocation fields, not request fields (T-405, issue #153).**
The correlation identifier, the duration metric and the log record are the places the
thesis becomes visible to an operator. Emit `kind`, an invocation identity, and the
binding's name; let status code be one field of the HTTP rendering rather than the
definition of the outcome. This ticket is also where correlation across an invocation
boundary starts being possible — an HTTP request that enqueues a job carrying its
identity into the job's metadata is the single most valuable thing about owning both
ends, and it costs nothing if the field exists from the start.

**4. Memoize the pipeline against a binding, not a route (T-500, issue #156).**
The ticket removes per-request container resolution by memoizing the resolved pipeline
on the compiled plan. Key that memo on the compiled binding, whatever addresses it, and
a subscription inherits the optimization the day it exists.

**5. Promote extension points under names that admit siblings (T-503, issue #159).**
Six extension points move into the supported surface. `AbstractHttpAdapter` is the right
name for the HTTP one provided the family it will join is decided now, so that the
adapter port promoted in 2.0 is not the one that has to be renamed in 2.1. Promote the
adapter port as the HTTP member of a family; do not promote a general-sounding name
around an HTTP-only shape.

**6. Do not implement `@Cache`, `@Idempotent` and `@Audit` as HTTP features (issue
#216).** The wave 4 decision was to say plainly that they do nothing rather than to make
them lie. Keep it. Idempotency is the defining cross-cutting concern of at-least-once
delivery, and implementing it against request headers first produces a design that the
event work has to replace. Its release is 2.4, where it is the feature rather than a
decoration.

One more, not a ticket: **make the layering check blocking** (issue #197). Nine
violations stand and nothing stops a tenth. Every claim in this roadmap about which
layer may see a transport is enforced by that script or by nobody.

## The contracts this roadmap adds

The contracts below carry the whole plan. Every release either adds one of them or is
the proof that one of them holds. The sketches are shapes, not signatures; the release
that lands one settles its exact form in its own tickets.

### The invocation

One unit of work, described without naming a transport. It lives in `contracts/`, which
may import nothing, so an adapter can be written against it alone.

```python
@runtime_checkable
class Invocation(Protocol):
    @property
    def kind(self) -> InvocationKind: ...        # http, job, event, socket, schedule
    @property
    def id(self) -> str: ...                     # identity the whole invocation is logged under
    @property
    def metadata(self) -> Mapping[str, str]: ... # headers, message attributes, job options
    @property
    def state(self) -> InvocationState: ...      # the open namespace HttpRequestState already is
    @property
    def deadline(self) -> Deadline | None: ...
```

`HttpRequest` keeps every member it has and satisfies this protocol. The change is who
is written against which: the scope manager, the execution context, the pipeline and
the executor are retyped from `HttpRequest` to `Invocation`, and the HTTP request
becomes what one entrypoint hands them.

The scope record moves with it. Per-invocation instance tables stop being attributes on
the transport's request object and become fields of a record the runtime creates when it
opens the scope and disposes of when it closes it. That single move is what makes a
scope available to a kind that has no request object, and it is the precondition for
deterministic teardown.

### The outcome

What the pipeline produces. A tagged union, because the alternative is a status code
that only one kind of entrypoint understands.

```python
type InvocationOutcome = Completed | Refused | Failed

@dataclass(frozen=True, slots=True)
class Completed:
    value: object

@dataclass(frozen=True, slots=True)
class Refused:
    reason: RefusalReason        # unauthenticated, forbidden, invalid, precondition, throttled
    detail: str

@dataclass(frozen=True, slots=True)
class Failed:
    error: Exception
    retryable: bool
```

**The pipeline never names a status code.** Rendering an outcome is the entrypoint's
job: the HTTP entrypoint maps `Refused(forbidden)` to 403 and a problem-details
document, exactly as wave 4 does today; a job entrypoint maps `Failed(retryable=True)`
to a retry with backoff and `Refused` to a dead-letter carrying the reason; a socket
entrypoint maps a failure to a close code. `ProblemDetailsExceptionFilter` becomes the
HTTP renderer of an outcome rather than the definition of failure.

`ExceptionFilter.catch` is public and returns `HttpResponse | None` today. The
migration is additive: from 2.1 a filter may return an outcome or an HTTP response, and
an HTTP response means `Completed` carrying it; from 3.0 an outcome is the only return.

### The scope algebra, extended

The existing algebra orders scopes by how wide a context each caches over and refuses
any edge from a wider owner to a narrower dependency. Two entries are added over the
roadmap, and the enforcement follows without new machinery.

| Scope | Caches over | Added in |
| --- | --- | --- |
| invocation | one unit of work | 2.1, as the widening of the current request scope |
| connection | one socket connection, many message invocations | 2.5 |
| durable | one partition key: a tenant, a customer, a stream | shipped |
| singleton | the process | shipped |
| transient | nothing, so it constrains nobody | shipped |

`REQUEST` stays the spelling an application writes. **Recommendation:** do not rename
the user-facing scope. It is the NestJS word, it is right for the kind most applications
start with, and renaming it costs every adopter a migration to buy a noun. Widen its
meaning — one invocation, whatever the trigger — say so in the documentation, and rename
the internals, where the noun is load-bearing and nobody outside depends on it.

Durable partitioning generalizes with the same move: `get_durable_context_key` takes an
invocation, so a tenant key can be read from a message attribute as easily as from a
`Host` header, which is what makes a per-tenant cache usable from a consumer.

### Task and stream ownership

The third claim, and the one with nothing behind it today. Two objects and three rules.

```python
class TaskScope(Protocol):
    def spawn(self, work: Callable[[], Awaitable[None]], *, name: str) -> None: ...
```

`TaskScope` is injectable and resolves at the scope of whatever asks for it. Injected
into an invocation-scoped provider, its tasks are joined before the invocation
completes and cancelled with its deadline. Injected into a singleton, they are joined at
shutdown, within the grace window graceful shutdown already defines.

1. **Work spawned through the runtime is joined by the scope that spawned it.** An
   invocation is not complete while a task it spawned is running.
2. **Escaping a scope is a separate verb.** Fire-and-forget exists, is called something
   else, and takes an explicit owner, so that a task outliving its request appears in a
   diff as a decision rather than as an omission.
3. **A stream is drained inside the scope that produced it.** An async iterator returned
   as a response body keeps its invocation scope open until it is exhausted or closed,
   and closing the scope closes the iterator. This is the fix for the current ordering,
   and it needs no port change: the runtime wraps the body, and the adapter still writes.

Deterministic teardown is the other half. Providers gain a disposable form — an async
generator that yields its instance and cleans up after, the shape Python already has for
this — and the scope disposes of what it built in reverse construction order when it
closes. Without it, "nothing outlives what it depends on" is enforced at construction
and unenforced at destruction, which is where connections actually leak.

### The entrypoint port family

`AdapterRoute` becomes one shape of a binding, and `AbstractHttpAdapter` one member of a
family:

```text
AbstractEntrypointAdapter      bind(bindings), start(), stop(), native(), capabilities
├── AbstractHttpAdapter        + from_native_request / to_native_response, path + methods
├── AbstractConsumerAdapter    + subscriptions, delivery dispositions (ack, retry, dead-letter)
└── AbstractSocketAdapter      + connection lifecycle, per-message invocations
```

A binding carries an address whose shape is the kind's — path and methods for HTTP,
topic and consumer group for events, queue and concurrency for jobs, channel for sockets
— a handler that takes an `Invocation`, and the requirements the framework checks
against `AdapterCapabilities` at startup. The capability check already exists and
already refuses at startup rather than at the first request that needs the missing
feature; every kind inherits it.

**Direct access stays direct.** `get_instance()` returns the transport's own object
today, and an application hosting several transports asks for the one it means. Nothing
is wrapped to protect the application from the platform, which is the fourth claim and
the reason `enable_cors` importing Starlette from the application layer has to be fixed
rather than copied.

### The consumer vocabulary

The non-HTTP analogue of `@Controller` and `@Get`, chosen so that the second claim is
observable in a diff rather than argued in a document:

```python
@Consumer()
class OrdersConsumer:
    def __init__(self, orders: OrderService, audit: AuditLog) -> None: ...

    @UseGuards(TenantIsolationGuard)
    @UseInterceptors(TimingInterceptor)
    @OnJob("orders.settle", concurrency=8)
    async def settle(self, job: Annotated[SettleOrder, Payload()]) -> None: ...

    @OnEvent("orders.placed", group="billing")
    async def placed(self, event: Annotated[OrderPlaced, Payload()]) -> None: ...
```

Same modules, same constructor injection, same scopes, same guards and interceptors and
pipes and filters, same validation, written the same way. `Payload()`, `Metadata()` and
`Ctx()` join `Body()` and `Query()` as binding markers, and a pipe that validates a
request body validates a message payload without being told which it got.

### Conformance per kind

The conformance matrix generalizes from adapters of one kind to adapters of every kind,
and the rule that made the HTTP port real becomes the rule for all of them:

> **A kind ships with two adapters or it does not ship.** One binds a real platform. One
> is in-process, depends on nothing outside the standard library, and lives in this
> repository forever. Both appear in the matrix and are held to the same answers.

The ASGI proof adapter is why the HTTP port is a port instead of a Starlette wrapper
with an interface drawn around it. An in-memory queue and an in-memory bus do the same
job for jobs and events, and they double as the testing surface adopters need in order
to test what they build on top.

## Releases

The order is a dependency order, not a calendar. Each release is one wave-shaped
programme run through the machinery the 2.0 backlog established: issues cut from
tickets, disjoint `Owns` sets, one agent per ticket, the pull request as the only
channel, the wave as a barrier. Cadence is the supervisor's to set; sequence is not,
because every release below is written against what the one before it produced.

| Release | Theme | The claim it makes true |
| --- | --- | --- |
| 2.0.0 | first production-ready release | the HTTP runtime, honestly described |
| 2.1 | the invocation | one composition model, in the contracts |
| 2.2 | lifetimes the runtime owns | tasks and streams |
| 2.3 | the second entrypoint: jobs | one pipeline, proved without HTTP |
| 2.4 | events and idempotency | at-least-once delivery, one pipeline |
| 2.5 | sockets and the connection scope | a scope wider than one message |
| 2.6 | schedules and multi-transport hosting | one application, several transports |
| 3.0 | the vocabulary settles | all four, in one set of names |

### 2.0.0 — finish the programme

Waves 4, 5 and 6 as the backlog writes them, plus the six adjustments under
`## Decisions to take inside the 2.0 programme`. Nothing from this roadmap is
implemented before the `2.0.0` tag. The reason is the audit: the repro harness becomes a
blocking gate in T-503, and a release that opens new subsystems while 91 findings are
still being closed cannot tell a regression from an unfinished migration.

### 2.1 — the invocation

**Theme.** Rename the unit of work in the contracts, the kernel and the runtime, with no
change to what an HTTP application sees. This is the release where the framework stops
being written against a request and starts being written against an invocation, and the
only observable difference is that a scope can now be opened by something that is not a
web server.

**Proof.** The conformance matrix answers identically on both adapters, before and
after, and the suite passes at the count it had, both quoted. Plus one new test that
drives an invocation through guards, pipes, interceptors, a handler and a filter with no
transport present at all — the first test in the repository that could not be written
today.

The tickets, at wave shape. `Owns` lists name the tree as it stands at `2.0.0`.

**R-100 The invocation contract.** Serial, blocks the rest of the release, as T-300 did
for ports and adapters. **Owns** new `src/bustan/contracts/invocation.py`,
`src/bustan/contracts/__init__.py`. Defines `Invocation`, `InvocationKind`,
`InvocationState`, `Deadline`, and the assertion that `HttpRequest` satisfies
`Invocation` unchanged. Imports nothing.

**R-101 The scope record.** **Owns** `src/bustan/kernel/ioc/scopes.py`,
`src/bustan/kernel/ioc/container.py`. Moves the per-invocation instance and controller
tables off `request.state` into a scope record the runtime creates and holds, keyed by
invocation identity; retypes `push_request`/`get_request_cache` and their siblings to
`Invocation` and renames them to say so. The public `REQUEST` token and
`request_context_id` keep their spelling and their meaning.

**R-102 The effective-scope table.** **Owns**
`src/bustan/kernel/ioc/planning/scopes.py`. Replaces the HTTP-named request-derived
tokens with invocation-derived ones, keeping `HttpRequest` and `HttpResponse` as members
rather than as the definition, so a provider that injects the invocation is scoped
correctly whatever produced it.

**R-103 The execution context tells the truth.** **Owns**
`src/bustan/pipeline/context.py`. `get_type()` returns a real kind;
`create_http` becomes one factory beside a neutral one; `switch_to_http()` keeps
working and gains siblings that raise a clear refusal until their kinds exist.

**R-104 Outcomes.** **Owns** new `src/bustan/contracts/outcomes.py`,
`src/bustan/pipeline/filters.py`, `src/bustan/runtime/execution.py`. Adds the outcome
union; lets a filter return an outcome or an HTTP response; moves problem-details
rendering behind the HTTP entrypoint. Behaviour on the wire is unchanged, and the
conformance matrix is the evidence.

**R-105 Disposable providers.** **Owns** `src/bustan/kernel/ioc/registry.py`,
`src/bustan/kernel/ioc/planning/annotations.py`, `src/bustan/kernel/ioc/runtime/`.
A provider may be an async generator that yields its instance and cleans up after it;
a scope disposes of what it built in reverse construction order when it closes. This is
the destruction half of "nothing outlives what it depends on", and 2.2 depends on it.

**Risk.** R-101 touches the container's hottest path and the benchmark gate from T-501
is the thing that catches a regression. Land the benchmark gate in 2.0 as the backlog
plans, or this release has no floor.

### 2.2 — lifetimes the runtime owns

**Theme.** Structured concurrency, end to end. A root task group opened in the
application lifespan; an invocation-scoped child group; `TaskScope` injectable and
resolving at the scope that asks; deadlines as cancel scopes, unifying the request
timeout wave 4 shipped; streams drained inside the scope that produced them; shutdown
draining in-flight invocations within the grace window before cancelling the rest.

**Ships also.** The `bustan doctor` rule for bare `asyncio.create_task` in application
code, added to the scanner T-504 builds — the point of the rule being that a task
nobody joins is now a diagnosable defect rather than a habit.

**Proof.** A test asserting that a request-scoped provider's connection is open while
its streamed body is being written and closed after the last byte; a test that shutdown
joins spawned work; a test that a deadline cancels a spawned task, not only the handler.

**Risk.** This is the release most likely to surprise an adopter, because it changes
when a handler is considered finished. **Recommendation:** the strict rule applies only
to work spawned through the runtime, `TaskScope` is opt-in for 2.x, and 3.0 is where a
detached task without a declared owner becomes an error.

### 2.3 — the second entrypoint: jobs

**Theme.** The first kind that is not HTTP, chosen to be the one that proves the most
and depends on the least. `@Consumer` and `@OnJob`; an in-process queue adapter in the
base package that needs no broker, no socket and no extra; job dispositions — complete,
retry with backoff, dead-letter — as the rendering of an outcome; the conformance suite
generalized to run a kind rather than a protocol; `bustan.testing` gaining a way to
dispatch a job through the whole pipeline in a test; observability emitting the same
invocation record it emits for a request.

Then, and only then, one real backend as an optional extra, the way Starlette is an
extra. **Recommendation:** whichever backend the first adopter actually runs. Do not
pick it from a feature matrix.

**Proof.** A guard, a pipe, an interceptor and a filter written once and used by an HTTP
route and a job handler in the same module, in a checked-in example that CI runs. That
example is the second claim; if it cannot be written, the claim comes out of the README.

**Risk.** The temptation to grow a queue rather than adapt one. Bustan binds queues; it
does not implement durability, and the in-process adapter says so in its own docstring.

### 2.4 — events and idempotency

**Theme.** `@OnEvent` with consumer groups, at-least-once delivery, partition keys
mapped onto durable scope, and dead-letter routing as an outcome rendering. Idempotency
becomes real here — `@Idempotent` backed by a storage port with the same shape the
throttler's storage already has — because at-least-once delivery is the setting where it
means something. `@Cache` and `@Audit` are settled in the same release, implemented or
removed, ending the decorative-decorator question the 2.0 programme deferred.

**Proof.** The conformance suite proves that redelivery of the same message runs the
handler once; the in-repo proof bus can redeliver on demand, so the test does not need a
broker.

**Risk.** Brokers differ where it matters: ordering, redelivery, acknowledgement
deadlines, group semantics. The mitigation is the mechanism that already exists —
capabilities declared per adapter and checked at startup, and a refusal rather than an
emulation when a binding asks for something the transport cannot do.

### 2.5 — sockets and the connection scope

**Theme.** A connection is a scope; a message is an invocation inside it. Adds the
connection scope to the algebra, flips `supports_websocket_upgrade` to true on both HTTP
adapters, and gives per-message invocations the same pipeline. Backpressure and close
codes are the socket rendering of an outcome.

**Proof.** A connection-scoped provider is built once per connection and disposed when
the socket closes, asserted on both adapters through the matrix.

**Risk.** Two nesting levels of scope is the point at which the algebra gets hard to
reason about by hand. It is also why the algebra is computed statically from a table:
the release adds a row and its rules, and the checker refuses what the rules refuse.

### 2.6 — schedules and multi-transport hosting

**Theme.** One application hosting several entrypoint adapters over one container and
one lifecycle: an HTTP server, a consumer, a scheduler. Scheduled ticks are invocations
like any other, which is nearly free once 2.2 owns tasks. Native access per transport;
`bustan graph` and the route snapshot generalized to bindings of every kind, so an
operator can see what an application listens to in one place.

**Proof.** An example application serving HTTP, consuming events and running a schedule
from one module graph, with one shutdown that drains all three.

**Risk.** Startup and shutdown ordering across transports is the failure mode — a
consumer that starts before the migrations finish, an HTTP server still admitting
traffic after the consumer has stopped. Readiness has to be per transport, which is why
health is a runtime concern in decision 2 rather than a route.

### 3.0 — the vocabulary settles

**Theme.** One break, taken deliberately, after the shape is known from four releases of
use rather than guessed at now. The candidates: renaming the public surface where
`request` is no longer the truth; making the outcome union the only filter return;
requiring a declared owner for detached tasks; consolidating the adapter family under
its final names; widening the Python floor.

The project has already decided how it takes a break: cleanly, with a migration guide
and `bustan doctor` rules rather than compatibility shims. Every rule is written as its
change lands, not afterwards, so the scanner is complete on the day the release is cut.

**Python floor.** The construct this roadmap found standing in the way is the PEP 695
`type` alias, which is 3.12 and later, so a 3.12 floor looks mechanical and a 3.11 floor
does not; the ticket that moves the floor establishes that by running the suite on the
interpreter rather than by trusting this paragraph. **Recommendation:** widen to 3.12
before the first non-HTTP adapter ships, because that is the release where adoption is
asked for, and decide about 3.11 from adoption evidence rather than in advance.

## Invariants that hold at every release

These are the gates. A release that cannot satisfy them ships without the feature that
broke one, not with the gate relaxed.

1. **Every adapter in the repository is in the conformance matrix, and every kind has
   two adapters.** An adapter that leaves the matrix rots into a false portability
   claim, which is the exact failure the ports work corrected.
2. **The layering check is blocking.** No package outside `adapters` imports a
   transport. The application layer included; `enable_cors` is the standing
   counterexample and its fix is the test of the rule.
3. **A pipeline stage never names a transport.** A guard, pipe, interceptor or filter
   that has to know it is running under HTTP is a design defect in the contract it was
   given, and is reviewed as one.
4. **A claim in the README is enforced by a test.** The 2.0 programme exists because
   the claims outran the code and an audit had to come and find it. A claim with
   nothing behind it is that defect being made again.
5. **The repro gate stays blocking**, and every new subsystem arrives with regression
   tests in the same shape: a script that fails before the fix and passes after.
6. **Benchmarks cover every kind**, and the regression threshold applies per kind. A
   consumer's throughput regression is as invisible as a route's was before T-501.
7. **Public surface changes are a three-file edit**: the module, the ordered export
   tuple, the regenerated reference. Additive within a major; one break at the major.
8. **The stability policy names every kind.** A promoted extension point is promoted for
   all of them or documented as belonging to one.

## What Bustan is not going to be

Saying this once, here, is cheaper than declining it release by release.

- **Not a data layer.** No ORM, no repository base classes, no migrations. It composes
  whatever the application chose.
- **Not a broker, a queue or a scheduler implementation.** The in-process adapters exist
  to prove the port and to make tests fast, and their docstrings say exactly that.
  Durability belongs to the platform underneath.
- **Not a resilience stack.** Retry and dead-letter dispositions are the rendering of an
  outcome the pipeline already produced. Circuit breakers, bulkheads and service
  discovery are the platform's, not the runtime's.
- **Not a benchmark contender.** Benchmarks exist to catch a regression against the
  previous release, not to win a comparison table.
- **Not a compatibility layer.** No shims, no dual spellings carried indefinitely. One
  break at a major, with a guide and a scanner.
- **Not a framework that hides the platform.** Direct access to the transport is a
  feature, and any wrapper that exists only to look neutral is deleted.
- **Not sync-first.** The model is async. Sync handlers run on the runtime's own limiter,
  which already exists, and that stays the whole of the sync story.

## Open decisions

Each of these changes what gets built. None blocks starting 2.1.

1. **Does `REQUEST` keep its spelling?** Recommendation: yes, widened in meaning, with
   the internals renamed. The alternative — `INVOCATION` as the user-facing scope, with
   `REQUEST` as an alias — buys precision at the cost of every adopter's migration and
   of the NestJS familiarity the project deliberately borrows.
2. **Which kind ships second: jobs or events?** Recommendation: jobs, because the
   in-process adapter needs no broker and the release therefore proves the second claim
   without adding a dependency. Events are a larger design surface and inherit the
   machinery.
3. **Is structured concurrency opt-in in 2.x?** Recommendation: yes, opt-in through
   `TaskScope`, with a doctor rule, and strict only at 3.0. The alternative changes when
   a handler is finished, in a minor release, for applications that never asked.
4. **Which broker is the first real adapter?** Recommendation: defer until an adopter
   names one. Every hour spent choosing it before then is spent on a matrix rather than
   on a user.
5. **Does 3.0 rename, or does 2.x carry both spellings?** Recommendation: rename at 3.0,
   once four releases of use have shown which names were wrong. Carrying both spellings
   is the compatibility layer this project has already decided against.

## Risks

- **One vocabulary over transports that genuinely differ.** Ordering, redelivery and
  acknowledgement semantics vary enough that a uniform model can become a polite lie.
  The mitigation is the mechanism that already exists: declare capabilities, check them
  at startup, and refuse rather than emulate.
- **Every kind is permanent.** The two-adapter rule multiplies maintenance by each kind
  added. A kind nobody uses is not free; it is a row in the matrix forever.
- **Structured concurrency changes the meaning of "done".** The most likely source of
  adopter surprise in the whole roadmap, which is why it stays opt-in until 3.0.
- **Scope complexity.** Five scopes and two nesting levels is more than a reader holds
  in their head. The static algebra is what keeps it honest, and it has to stay ahead of
  the features rather than catch up after them.
- **Starting before 2.0 is finished.** The audit gate is still closing. Design work here
  is safe; implementation before the tag is not.
- **Documentation drift across kinds.** One pipeline described four times diverges. The
  behavioural documentation is written once against the invocation, with per-kind
  sections that state only what differs.
