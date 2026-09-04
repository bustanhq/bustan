# Security Policy

## Reporting A Vulnerability

Do not open a public GitHub issue for security vulnerabilities.

Report security issues privately to `security@bustan.dev` with:

- a clear description of the issue
- impact and affected surface
- reproduction steps or proof of concept if available
- any suggested mitigation if you already have one

You should receive an acknowledgement within 5 business days.

## Disclosure Process

- The maintainer will confirm whether the report is a security issue.
- Fixes will be prepared privately when possible.
- Public disclosure should wait until a fix or mitigation is available.
- Credit will be given for responsible disclosure unless you request otherwise.

## Advisories

### Cross-request identity disclosure in the injection container

**Affected version:** `1.1.0`. **Fixed in:** `1.1.1`. **Severity:** critical.

A controller declared without `scope=` defaults to singleton and is built once for the life of
the process. The container exempted controllers from its scope guard, so such a controller was
allowed to inject a request-scoped provider and then keep the first caller's instance. Every
later caller was served the first caller's request-local state, including any identity derived
from a header. An application that resolves the caller in a request-scoped provider and injects
it into a default-scope controller discloses one user's identity to every other user.

Four related weaknesses shared the same root cause and are fixed in the same release:

- A `use_class` provider dict ignored the target class's declared scope and registered it as a
  singleton, so a class written to be per-request became process-wide without a diagnostic.
- The scope guard rejected only request-scoped dependencies, so a singleton could capture a
  tenant-keyed durable instance and serve one tenant's partition to every other tenant.
- A durable provider could inject the `Request` and retain it for the life of its partition,
  exposing the first caller's headers, including `Authorization`, to everyone routed there.
- `@Controller(scope=Scope.DURABLE)` was accepted and then treated as a singleton, so one
  instance was shared across every tenant partition it was declared to separate.

Two availability weaknesses are fixed alongside them: the durable instance store and its
per-partition construction locks were unbounded dictionaries keyed by a value the provider
derives from the request, so an unauthenticated caller who rotated one header could grow both
without limit.

**Vulnerable shapes.** Check for any of these in an application on `1.1.0`:

- a `@Controller` with no `scope=` whose constructor takes a request-scoped provider
- a `@Controller` with no `scope=` whose constructor takes Starlette's `Request`
- a provider dict `{"provide": Token, "use_class": Cls}` where `Cls` is declared
  `@Injectable(scope="request")` or `@Injectable(scope="durable")`
- a singleton provider whose constructor takes a durable-scoped provider
- an `@Injectable(scope="durable")` provider whose constructor takes `Request`
- a `@Controller(scope=Scope.DURABLE)`
- a singleton owner reaching request-scoped state through a transient provider or a
  `use_existing` alias, which look harmless at the first hop
- a `use_factory` provider whose `inject` list names a provider shorter-lived than the scope
  the factory's result is cached under

**Upgrading.** `1.1.1` refuses each of these while the application is being assembled rather
than at request time, so an affected application fails at start-up with a message naming the
owner, the parameter and the two scopes involved. Declare the controller or provider with a
scope no wider than what it holds; `docs/REQUEST_SCOPED_PROVIDERS.md` states the rules and
`docs/TROUBLESHOOTING.md` maps each message to its fix.

**Mitigation without upgrading.** Declare `scope=Scope.REQUEST` on every controller that
injects request-scoped state, and give every durable provider a partition key drawn from an
authenticated value rather than an unauthenticated header.

## Supported Versions

While Bustan is currently in alpha (`v1.x`), security support is best-effort for:

- the default branch
- the most recent tagged release

`1.1.0` is affected by the advisory above and is superseded by `1.1.1`. Older unreleased
snapshots and abandoned feature branches are not supported.