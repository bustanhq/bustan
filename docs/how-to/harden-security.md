# Security Hardening

What a `Bustan` application refuses by default, what it will not refuse until you say
so, and what it does not do at all. The order matters: the last section is the one that
gets deployments hurt, because it is the set of protections people assume are there.

The framework's own vulnerability-reporting policy is in
[SECURITY.md](../../SECURITY.md); this document is about the application you build with
it.

## The Defaults You Already Have

An application that configures nothing runs under all of these.

| Protection | Default | Section |
| --- | --- | --- |
| Request body size | 1 MiB, then `413` | [Request Limits](#request-limits) |
| Upload size | 10 MiB, then `413` | [Request Limits](#request-limits) |
| Upload part count | 20, then `413` | [Request Limits](#request-limits) |
| Request timeout | 30 s, then `504` | [Request Limits](#request-limits) |
| Synchronous handler threads | 40 | [Request Limits](#request-limits) |
| Body field type checking | on, then `400` | [The Boundary Is Validated](#the-boundary-is-validated) |
| Internal detail masked in refusals | on | [Refusals Say Nothing Useful To An Attacker](#refusals-say-nothing-useful-to-an-attacker) |
| Credential redaction in logs | on, by key name | [What Never Reaches A Log](#what-never-reaches-a-log) |
| Throttling | **off** | [Throttling](#throttling) |
| CORS | **off** | [CORS](#cors) |
| Authentication | **off** | [Authentication And Authorization](#authentication-and-authorization) |

## Request Limits

Every bound is finite, because the alternative to a limit is not "no limit" but "the
limit the caller picks": a body size, a number of uploaded parts and a running time are
all chosen by whoever sent the request, and all three are paid for in this process's
memory and threads.

```python
from bustan import RequestLimits, create_app

app = create_app(
    AppModule,
    request_limits=RequestLimits(
        max_body_bytes=8 * 1024 * 1024,
        max_upload_bytes=64 * 1024 * 1024,
        max_upload_files=8,
        timeout_seconds=15.0,
        sync_handler_threads=40,
    ),
)
```

| Field | Default | What it bounds |
| --- | --- | --- |
| `max_body_bytes` | 1 MiB | The body read to bind ordinary parameters. |
| `max_upload_bytes` | 10 MiB | The body read to parse a multipart form. Separate from the above, so a route accepting uploads does not raise the ceiling on every other route. |
| `max_upload_files` | 20 | How many parts of a form may bind to one parameter. |
| `timeout_seconds` | 30.0 | Wall clock one request may take before it is abandoned and answered through the route's exception filters. |
| `sync_handler_threads` | 40 | How many synchronous handlers may run at once. |

The limits belong to the application rather than to the process, so a second application
in the same process can serve under different ones. A value of zero or less is refused
where it is written rather than once per request, because it refuses every request
rather than bounding one.

**`None` removes a bound.** Do it only for a deployment that has measured that it needs
to, and never as a way of making a failing test pass. It is never what an application
gets by not choosing.

**A synchronous handler cannot be interrupted.** Python cannot cancel a thread, so
`timeout_seconds` is enforced for a synchronous handler only once it returns. What
bounds one that never returns is `sync_handler_threads`, which caps how many can be
occupying threads at the same time. If your handlers do blocking work, that ceiling is
the real limit on how much of the process one slow dependency can take.

## The Boundary Is Validated

A body field whose value does not match its declared type is answered `400`, not passed
to the handler. A nested object arrives as the type its field declares rather than as a
plain mapping. The offending field is named in the problem's `errors` array.

This is worth stating in a security document because the alternative is worse than a
type error: a handler annotated `int` that is handed a `str` behaves in whatever way its
own arithmetic and comparisons happen to behave, and reaches the database with that
value. See [reference/routing.md](../reference/routing.md) for the binding and validation modes, and
[reference/errors.md](../reference/errors.md) for what a binding failure looks like.

## Refusals Say Nothing Useful To An Attacker

Every refusal is answered as RFC 9457 problem details:

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

Three rules hold:

- **A message on a 5xx never reaches the caller.** Statuses at 500 and above report a
  fault in the application rather than anything the caller can act on, and their
  messages routinely name internal detail. The status reason is returned instead and the
  message is kept in the log.
- **A refusal does not name what refused it.** A guard rejection is answered
  `"Forbidden"`, and the guard's class name goes to the log against the request's
  correlation id. The caller being refused is the one party those names must not reach.
- **A `ForbiddenException` you raise yourself should follow the same rule.** Say what is
  refused, never why in terms of your own roles or permissions.

"Every refusal" includes the ones decided before a handler runs: a path no route
answers, a method no route answers and a version nothing serves are all answered with
the problem document their status names, on every adapter. See
[reference/routing.md](../reference/routing.md#refusals-before-a-handler-runs). A caller probing for paths
therefore learns from a `404` only that nothing answered, which is what it would learn
from a line of text, and every refusal it can provoke is masked by the same three rules.

`HttpException` and its subclasses in `bustan.errors` fix the status, the problem type
and the code, so the same condition is always reported the same way. Reach for one of
those rather than returning a hand-built error body, and the answer stays consistent
across the whole application.

## Authentication And Authorization

Off unless you wire it. The policy decorators declare what a route needs; a registry you
bind provides the code that identifies a caller.

```python
from bustan import Auth, Controller, Get, Permissions, Public, Roles


@Controller("/orders")
@Auth("bearer")
class OrderController:
    @Get("/")
    @Roles("operator")
    def list(self) -> list[dict[str, object]]: ...

    @Get("/public-status")
    @Public()
    def status(self) -> dict[str, str]: ...
```

| Decorator | What it means |
| --- | --- |
| `@Auth(strategy)` | Serve only to a caller the named authenticator identifies. The principal it returns is what the checks below read. |
| `@Roles(*roles)` | Every named role must be held. Naming two means both, never either. |
| `@Permissions(*permissions)` | The same, over permissions. The container never interprets either; what goes in each is your choice. |
| `@Public()` | Skip authentication and the role and permission checks. On a handler it outranks the controller. |

Roles and permissions written on the controller and on the handler **add up**, so a
handler narrows what its controller requires and can never widen it. `@Public()` written
beside an access requirement at the same level is contradictory and refused while the
routes are compiled.

**`@Public()` waives this policy, not every gate.** Guards you register yourself still
run.

### 401 Versus 403

| Situation | Answer |
| --- | --- |
| No usable identity presented | `401` with a `WWW-Authenticate` challenge |
| An identified caller lacking a role or permission | `403` |
| A route whose authenticator registry is missing or names an unknown strategy | `500`, and the reason in the log |

The third row is deliberate. Nothing about the request reached that point: the wiring is
missing, so every caller of the route is refused whatever it sends. Reporting that as a
refusal of the caller would hide the mistake behind the answer a wrong password gets.

An application whose authenticated route cannot see an authenticator registry is refused
at build time, so the misconfiguration usually never reaches a request at all.

The default challenge names the bearer scheme. Pass `headers` to
`UnauthorizedException` to state the scheme you really use.

## Throttling

Off unless you install it.

```python
from bustan import ThrottlerModule


ThrottlerModule.for_root(
    ttl=60,
    limit=100,
    storage=RedisThrottlerStorage(),
    trusted_proxies=["10.0.0.0/24"],
)
```

A caller over the limit is refused `429` with `Retry-After`, and every answer carries
`X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Reset`.

### Two Ways To Get It Wrong

**Running more than one worker with the in-process store.** The default store counts
each worker separately, so N workers allow N times the limit. Pass a `storage`
implementation every worker can see. The contract is one asynchronous
`count_request(key, ttl, limit)`; where processes share the store, counting and
reporting must happen as one atomic operation, or two workers racing on one key will
both be told they are within the limit. See
[how-to/migrate-from-1x.md](../how-to/migrate-from-1x.md#throttlerstorage) for the full contract.

**Setting `trusted_proxies` too wide.** It is empty by default, which counts every
request under the address it arrived from and ignores forwarding headers entirely. Set
it to the load balancer you actually sit behind, as the peers you accept connections
from, and never to a wide block: **any peer in this list can put any address in
`X-Forwarded-For` and be counted as that caller**, so listing a peer an attacker can
connect from lets that attacker spend somebody else's allowance or evade its own limit.

The header is read only once the peer that sent it is trusted, and it is read from the
right, because each proxy appends the address it saw and only the entries a trusted
proxy wrote are worth anything.

A `key_resolver` of your own replaces the derivation of the key altogether, and is then
responsible for its own trust decisions: `trusted_proxies` is not consulted.

### Memory Is Bounded, And Bounded Has A Cost

An unauthenticated caller chooses the key it is counted under by choosing where it
connects from, so the in-process store holds at most `max_keys` keys - 10,000 by default
- and discards the least recently used beyond that. A refused request is never recorded,
so a key holds at most `limit` timestamps.

**Evicting a key forgets what its caller has spent.** Keep `max_keys` comfortably above
the number of callers you expect in one window, or a caller whose key is evicted starts
again with a full allowance.

### Per-Route Budgets

`@RateLimit(limit=..., window=...)` counts a route under a key of its own, so a request
spends that budget instead of the application-wide one rather than as well as it. The
window is a whole number of seconds or a whole number followed by `s`, `m`, `h` or `d`,
and one the framework cannot read stops the build rather than answering `500` on every
request the route serves.

An application that has not installed throttling records the policy and enforces
nothing, so a route that must be bounded needs both.

## CORS

Off unless you enable it, and `enable_cors()` with no arguments is **refused** rather
than read as every origin:

```
ValueError: enable_cors needs the origins it should permit. Pass
CorsOptions(origins=[...]), or omit the call to leave cross-origin requests refused.
```

`CorsOptions` names no origins until you name them, so a policy that permits every page
on the internet is one you wrote rather than one you inherited. Every other field has a
default, listed in the [API reference](../reference/api.md#corsoptions).

```python
from bustan import CorsOptions

app.enable_cors(
    CorsOptions(
        origins=["https://console.example.com"],
        credentials=True,
        allowed_headers=["authorization", "content-type"],
    )
)
```

A public read-only API that really does serve every origin writes `origins=["*"]` and is
served. `credentials=True` with `origins="*"` is the combination to avoid. Name the
origins.

## What Never Reaches A Log

Log records are JSON, encoded, so a user-supplied newline cannot end one record and
begin another - which is how log forging works and what the previous format allowed.

Field values are withheld by key name, at any depth, for a default set covering
`authorization`, `password`, `token`, `api_key`, `set-cookie` and the rest. Replace the
whole set with `Logger.set_redacted_keys(...)`.

**Redaction reads names, not values.** A credential embedded inside a value - a
connection string, a URL with a password in it, a command line - is printed in full.
Do not log those, redaction will not save you. The same limit applies to `bustan config`,
which additionally reports the whole process environment; see
[reference/cli.md](../reference/cli.md#bustan-config).

[how-to/observe-an-application.md](../how-to/observe-an-application.md#redaction) has the details.

## Probes Are Not Authenticated For You

`GET /health/live` and `GET /health/ready` skip throttling, because a rate-limited probe
reports a healthy process as failed. **They do not skip your guards**, and the framework
does not authenticate them either way. An application that authenticates every request
must exclude these two routes itself; one that exposes them to the internet is
publishing which of its dependencies are down.

A probe's `detail` string crosses a trust boundary. Never put a host name, a connection
string, a credential or a dependency's exception message in one.

## What This Framework Does Not Do

Assume none of the following unless you have arranged it yourself.

- **TLS.** Terminate it in front of the application.
- **Security response headers.** No `Strict-Transport-Security`, `Content-Security-Policy`,
  `X-Content-Type-Options`, `X-Frame-Options` or `Referrer-Policy` is written. Add them
  at the proxy or in a middleware.
- **CSRF protection.** There is none. A cookie-authenticated browser application needs
  its own.
- **Session management.** There is no session store and no cookie handling beyond
  reading what a request carries.
- **Password hashing, token issuing or token verification.** `@Auth` runs the
  authenticator you wrote; the framework has no opinion about what is inside it.
- **Request signing, replay protection or nonce tracking.**
- **`@Cache`, `@Idempotent` and `@Audit` do nothing in this version.** All three accept
  every argument and record their policy on the route's compiled plan, and nothing in
  the request path reads it. A route marked `@Idempotent` runs its handler again on a
  retry and its side effect happens again; a route marked `@Audit` leaves no record of
  who called it. Deduplicate inside the handler and write the audit record yourself
  until that changes. Their docstrings say the same thing, which is what an editor's
  hover shows.
- **`@Owner` and `@DeprecatedRoute` write no response header** and are read only by the
  governance ownership report.

## Before You Ship

- Request limits are the ones you chose, or the defaults fit what your routes accept.
- Throttling is installed, with a shared store if you run more than one worker.
- `trusted_proxies` names your load balancer and nothing wider.
- CORS names your origins, or is off.
- Health routes are not reachable from the internet, or carry nothing sensitive.
- Nothing you log embeds a credential inside a value.
- Every `@Idempotent` and `@Audit` route has the behaviour written by hand.
- Your error responses have been read by someone asking what they tell an attacker.

## Where To Go Next

- [how-to/observe-an-application.md](../how-to/observe-an-application.md) - logging, redaction, and what the probes report.
- [how-to/deploy.md](../how-to/deploy.md) - workers, proxies, draining.
- [reference/request-pipeline.md](../reference/request-pipeline.md) - where guards and filters run.
- [how-to/migrate-from-1x.md](../how-to/migrate-from-1x.md) - which of these are new since 1.x.
