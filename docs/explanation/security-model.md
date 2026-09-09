# What The Security Model Does And Does Not Cover

Two things are worth understanding before configuring anything: what a refusal deliberately withholds from a caller, and where the framework's responsibility stops.

For the settings themselves, see [Harden An Application](../how-to/harden-security.md).

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
