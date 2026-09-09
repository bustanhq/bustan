# Changelog

> [!IMPORTANT]
> Versions `1.0.0` and `1.0.1` were unintentionally released during CI/CD setup. Treat them as early alpha orphans. The first production-ready, non-alpha release target remains `2.0.0`.

## [2.0.0-rc.7](https://github.com/bustanhq/bustan/compare/v1.1.0...v2.0.0rc7) (2026-09-09)

The 2.0.0 release, published as a candidate. Six milestones stand behind it, and this entry carries
all of them: the candidates `2.0.0-rc.2` through `2.0.0-rc.6` were published from `main` as the work
landed, and their sections are merged here rather than kept beside this one.

An application written against `1.x` does not start on 2.0. That is the decision the release was
built on, and [migrate-from-1x.md](docs/how-to/migrate-from-1x.md) sets every construct that changed
beside its replacement. `bustan doctor [path]` finds most of them in a codebase by parsing it rather
than importing it, since the code it looks for is exactly the code that no longer imports, and it
prints the edit that answers each finding.

> [!NOTE]
> `1.1.1` was published on 2026-09-04 from a branch that was never merged to `main`, and no
> changelog entry or version bump followed it. The four fixes it carried were ported into `main`
> under [#62](https://github.com/bustanhq/bustan/issues/62), listed below, so this release supersedes it. `main`'s version files read
> `1.1.0` until the first candidate; they now read `2.0.0rc7`.

**The six milestones, in the order they emptied.**

* **2.0.0-rc.1 - foundation and the plan-then-execute kernel** (19 issues). It emptied without ever
  being tagged, so its work shipped in the first candidate published from `main` rather than in a
  release of its own.
* **2.0.0-rc.2 - the resolution kernel's remaining defects** (15 issues).
* **2.0.0-rc.3 - ports and adapters** (34 issues). The transport becomes replaceable rather than
  assumed: a contracts package, a narrowed adapter port, a second adapter written against the ASGI
  specification and the standard library alone, a conformance matrix that holds both adapters to the
  same answers, an enforced layering rule, Starlette demoted to an optional extra, and the package
  layout move the rest of the wave was gated behind. It also closed a defect shipped in `2.0.0rc2`:
  without the `starlette` extra installed, the framework could not compile a single route.
* **2.0.0-rc.4 - the request contract and operability** (26 issues). A request now has one error
  contract from the edge to the handler and back, an exception hierarchy that reaches every common
  status without naming internals in a refusal, finite limits on what one request may spend, health
  and readiness a scheduler can route on, a shutdown that drains rather than drops, observability
  that measures what a request cost and can be correlated across services, and a throttler that
  counts what a deployment actually served. It also closed the last of the request-binding gaps: a
  handler is no longer handed a value whose type contradicts its own annotation.
* **2.0.0-rc.5 - the audit is closed** (6 issues). Every defect the September dependency-injection
  audit demonstrated is fixed and held there by the script that used to reproduce it, and the CI job
  that runs those scripts stopped being advisory: it is a regression gate, and a finding that comes
  back fails the build rather than appearing in a summary nobody reads. The rest is what an
  application built on this framework needs from it that had no answer before. A route's pipeline is
  resolved once instead of once per request. The framework can be measured, and a regression in what
  it costs fails CI. Five extension points an enterprise must customise reached the supported
  surface, and the surface now derives from a written policy rather than drifting alongside one. The
  command-line tool can answer questions about the application in front of it.
* **2.0.0 - the pre-release audit and the layering debt** (33 issues). An adversarial audit of the
  candidates, the layering debt the first five carried, the documentation the release is adopted
  through, and the last behaviour a decorator promised without delivering.

**This release carries fourteen breaking changes.**

* **The package layout moved, and Starlette is an optional extra.** Four packages were renamed, and
  installing `bustan` no longer installs a web server: `uv add 'bustan[starlette]'` adds the
  Starlette adapter, and an application can run on the framework's own raw ASGI adapter without it.
  Every install instruction in the repository under-installed before this and now names the extra.
* **A provider is a value type rather than a dict.** `ClassProvider`, `FactoryProvider`,
  `ValueProvider` and `ExistingProvider` are exported, and each takes `provide` and exactly one
  target, with `scope` and `inject` only where the runtime honours them. A dict is refused with a
  message naming the type that replaces it. The dict spelling carried two of the September audit's
  confirmed findings, and both become unwritable rather than fixed: a wrong key, a missing token or
  two targets is now an error the type checker reports where the provider is written.
  [migrate-from-1x.md](docs/how-to/migrate-from-1x.md) shows all four beside their replacements.
* **A `ModuleRef` injected into a provider or a controller names the module that class was declared
  in**, not the root module. A reference asked of the application directly still names the root.
  Code reading `ModuleRef.module_key`, or relying on an injected reference resolving through the
  root, sees a different module.
* **`strict=False` widens a token its own module cannot see** into a search of every module in the
  application, and refuses to choose when more than one declares it, naming `for_module()` as the
  way to say which. It previously fell back to what the root module could see, which widened
  nothing. A lookup that used to return a root-visible provider may now return a different one or
  raise.
* **Every application now serves under finite request limits.** A body over one megabyte, an upload
  over ten, more than twenty parts bound to one parameter, or a request running longer than thirty
  seconds is refused where it previously was not. `bustan.adapters.asgi` no longer exports
  `RequestBodyTooLarge`, and an oversized body is answered `413` rather than `500`.
* **A request body whose field values do not match their declared types is answered `400`** rather
  than passed to the handler, and a nested object arrives as the type its field declares rather than
  as a plain mapping.
* **`bustan.errors` exports nineteen new names.** A request refused for want of an identity is
  answered `401` with a `WWW-Authenticate` header where it was answered `403`, and an application
  whose authenticated route cannot see an authenticator registry is refused at build time.
* **`ThrottlerStorage` declares one asynchronous `count_request(key, ttl, limit)`** in place of
  `increment` and `get_ttl`. An implementation of the old protocol must be rewritten.
* **`RequestTracer` and `TraceSpan` are reshaped to OpenTelemetry's span model.**
  `MetricsSink.record_request` gains a `duration_seconds` keyword, and a sink written without it is
  still called with the labels alone rather than broken. `Logger` emits structured JSON through the
  standard library rather than a formatted line through `print()`.
* **`Application.close()` stops a running server**, drains it and waits for its port to be released,
  where before it ran the lifecycle teardown alone and left the server serving. Shutdown hooks
  receive the name of the signal that stopped the process.
* **`enable_cors()` with no origins raises** instead of permitting every origin. The default was `*`
  on both a simple request and a preflight, against a stated deny-by-default standard and the
  hardening guide's own advice to name the origins. The refusal is a `CorsConfigurationError`,
  exported so an application can catch it by name, and every `CorsOptions` default is now written in
  the docstring the API reference is generated from.
* **A cross-origin policy is the transport adapter's work.** `enable_cors` is a port method that
  refuses by default, so an adapter that does not implement it declines by name rather than
  accepting silently. The raw ASGI adapter gained its own implementation, and `CorsOptions` moved to
  `bustan.contracts.cors` with its meaning unchanged.
* **`@Cache`, `@Idempotent` and `@Audit` do what they say.** All three recorded a policy on the
  route's compiled plan and changed nothing about the request, so an application that wrote
  `@Audit(event="user.delete")`, saw it accepted and shipped it had no audit trail; `2.0.0-rc.4`
  stated that absence in each docstring, and this release ends it. Each now attaches the interceptor
  that carries it out, and that interceptor reads the same compiled plan the policy guard and the
  throttler read. **A route carrying any of the three ran its handler on every request in every
  earlier release and no longer does.** `@Cache` answers a repeated `GET` or `HEAD` with the
  previous answer until its ttl passes, kept apart by route, path, query string and the caller the
  request was authorised for. `@Idempotent` answers a retry presenting a key already seen with what
  the first attempt returned, for twenty-four hours. `@Audit` writes one record through the
  framework's logger once the handler has run, whether it returned or raised, carrying the event
  name and the caller and nothing the caller sent. Both stores are in the process, bounded per
  decorated route, and shared with no other worker and no later run, so a deployment relying on
  either across its workers still needs a store of its own. `@Cache` refuses a ttl below one second
  where it is written, and is refused on a route returning a response object or a stream, because
  such a body can only be read once.
* **The container's tables are read through its views.** The registry's `bindings`,
  `module_visibility` and `controller_modules`, and the scope manager's three instance caches, are
  private. The views - `binding_view`, `visibility_view`, `controller_module_view` and the three
  cache views - are the supported read path and each raises on a write, so a table can no longer be
  corrupted through the attribute that was the only way to read it.

**Not breaking, and worth knowing.** A mapping written where a factory's `inject` token belongs is
refused while the module is compiled, naming the module, the token and the entry; it previously
reached the visibility lookup as `TypeError: unhashable type: 'dict'`. A dynamic registration may
now replace a provider its base module declares rather than colliding with it. `INQUIRER` yields the
requesting class rather than the requesting instance, documented in
[comparisons.md](docs/explanation/comparisons.md) as a deliberate difference from NestJS: this
framework injects through the constructor only, so at the moment the token is answered the
consumer's `__init__` has not run and no instance of it exists.

**The request path answers one error contract.** An unmatched route and a wrong method were answered
as `text/plain` while every framework error was problem details, so a client written against the
documented model broke on the error it meets first. All three refusals, including an unknown API
version, now answer with the same document on both adapters, and the `Allow` header no longer
differs between them. Three conformance cases compare the media type and the whole body rather than
the status, which is why the old suite reported both adapters answering identically throughout.

**The two transports route and redirect alike.** The raw ASGI adapter matched routes against
undecoded bytes while the Starlette adapter ran under a server that decodes first, so the same
request reached different routes on the two transports; one parser now decodes the target for both
scope builders, per segment so that an encoded separator cannot create a boundary, and refuses a
non-ASCII request line rather than routing mojibake. Both adapters answer a trailing-slash redirect
with a relative `Location`, no content type on an empty body, and a redirect for a single trailing
slash only. Neither difference was visible to the conformance matrix, because both adapters were
wrong in the same way; the cases that cover them now name the headers that carry the difference.

**The layer table is enforced.** The check spent five candidates advisory, reporting ten findings
nobody was obliged to read. The report is empty, `continue-on-error` is gone, and a change that
crosses a layer fails the build. The conformance suite left the runtime, the kernel stopped reading
controller metadata out of it, the runtime stopped naming two application types, and the health
package is classified.

**Two leaks, two wrong objects, and an extension point nothing could extend.** The read-only
discovery surface printed a dynamic module's entire configuration, including every value a
configuration module resolved. A transport request annotation was matched by shape, so one adapter
handed over the other adapter's request object and never recognised its own, on a handler parameter
and on a provider constructor alike. A singleton injecting `ModuleRef` could not be served over HTTP
at all, because the path `create_app` takes did not push the application during startup. An
application can now install its own `ResponseSerializer`, which was on the supported surface with no
supported way to install one.

**The documentation is organised on diataxis** with kebab-case names, six tutorials that grow one
link shortener from a scaffold to something deployable, and one package manager described
throughout. Five documents did not exist before the last milestone - migration, architecture,
observability, security hardening and deployment - and nine statements contradicted by behaviour are
corrected. `SECURITY.md` and the versioning reference state their promises against a policy rather
than a release phase, so shipping a version cannot make them stale. The post-publish verification
that failed the good `2.0.0rc5` release now waits fifteen minutes with backoff and tells a missing
upload apart from a slow index.

Every entry below is a closed issue from one of the six milestones, grouped by the classification
label it carries rather than by the milestone it closed on. What is not listed: the epics that group
the waves, one report closed as a duplicate of another in the same milestone, and
[#197](https://github.com/bustanhq/bustan/issues/197), the tracker the layering work was split out
of, whose five children are listed. An issue carrying two classification labels appears once, under
the more severe of them; [#32](https://github.com/bustanhq/bustan/issues/32) carries none and is
listed under Documentation, where its change landed.

### Security

* T-103 Effective scope algebra ([#45](https://github.com/bustanhq/bustan/issues/45))
* 2.0.0 would ship without four fixes that 1.1.1 already has: CR-01, RI-02, RI-05, RI-12 ([#62](https://github.com/bustanhq/bustan/issues/62))
* RI-10: a durable-scoped controller with no context-key hook is served as one instance to every tenant ([#64](https://github.com/bustanhq/bustan/issues/64))
* EX-04: a 403 body names the guard's dotted class path and the auth strategy, with debug off ([#65](https://github.com/bustanhq/bustan/issues/65))
* a body field is never checked against its declared type, so a handler is handed an int that is a str ([#103](https://github.com/bustanhq/bustan/issues/103))
* audit the resolved dependency set of the root project and all six examples in CI, from their committed lockfiles, so an advisory is found before a release rather than after one ([#121](https://github.com/bustanhq/bustan/issues/121))
* constructor failures bypass every filter, and a rejected request still pays for its providers ([#148](https://github.com/bustanhq/bustan/issues/148))
* only four HTTP statuses are reachable, and the 403 body leaks internal role names ([#149](https://github.com/bustanhq/bustan/issues/149))
* no body-size limit, no upload cap and no timeout, so one large POST is an out-of-memory vector ([#152](https://github.com/bustanhq/bustan/issues/152))
* request duration is never measured, and a user-supplied newline forges log records ([#153](https://github.com/bustanhq/bustan/issues/153))
* the throttler multiplies its limit by worker count and shares one bucket behind a load balancer ([#154](https://github.com/bustanhq/bustan/issues/154))
* a body that declares no length is read in full on the default adapter before the limit refuses it ([#211](https://github.com/bustanhq/bustan/issues/211))
* the ASGI adapter reads a body 4096 times the application's limit before anything refuses it ([#217](https://github.com/bustanhq/bustan/issues/217))
* the release workflow gates six publish steps on a string that is always truthy, so any push could publish whatever version the project file names ([#39](https://github.com/bustanhq/bustan/issues/39))
* `DiscoveryService.modules()` prints a dynamic module's entire configuration, secrets included, to every caller of a read-only surface ([#259](https://github.com/bustanhq/bustan/issues/259))
* `enable_cors()` with no arguments allows every origin ([#305](https://github.com/bustanhq/bustan/issues/305))
* the raw ASGI adapter matches routes against undecoded bytes, so the two transports route the same request to different places ([#326](https://github.com/bustanhq/bustan/issues/326))

### Correctness

* T-001 Formatting and lint baseline ([#27](https://github.com/bustanhq/bustan/issues/27))
* Follow-up: scope validation is skipped for a graph with no controllers ([#33](https://github.com/bustanhq/bustan/issues/33))
* T-003 Shared test fixtures ([#35](https://github.com/bustanhq/bustan/issues/35))
* T-004 Stop the suite defending the defects ([#41](https://github.com/bustanhq/bustan/issues/41))
* T-101 One source of visibility truth ([#43](https://github.com/bustanhq/bustan/issues/43))
* T-102 Annotation resolution engine ([#44](https://github.com/bustanhq/bustan/issues/44))
* T-100 Provider normalization and token identity ([#47](https://github.com/bustanhq/bustan/issues/47))
* Follow-up: a local binding silently shadows an imported export of an equal token (PN-11, cross-module half) ([#55](https://github.com/bustanhq/bustan/issues/55))
* Follow-up: a durable provider with no context key hook is still accepted at bootstrap ([#56](https://github.com/bustanhq/bustan/issues/56))
* Follow-up: ControllerFactory still reads provider metadata with an inheriting getattr ([#57](https://github.com/bustanhq/bustan/issues/57))
* CR-06 remainder: an unhashable durable context key surfaces as a raw TypeError ([#66](https://github.com/bustanhq/bustan/issues/66))
* T-200 Lifecycle correctness ([#67](https://github.com/bustanhq/bustan/issues/67))
* T-202 Testing surface delegates to the lifecycle ([#68](https://github.com/bustanhq/bustan/issues/68))
* T-201 Override semantics ([#69](https://github.com/bustanhq/bustan/issues/69))
* T-203 Global pipeline providers resolve per request ([#70](https://github.com/bustanhq/bustan/issues/70))
* Follow-up: resolving between a shutdown and the next startup hands back an uninitialized provider ([#75](https://github.com/bustanhq/bustan/issues/75))
* Follow-up: the route scanner has no notion of framework hooks, so any future one reads as an undecorated route method ([#76](https://github.com/bustanhq/bustan/issues/76))
* Follow-up: available_providers still keys by equality after the token-identity change ([#77](https://github.com/bustanhq/bustan/issues/77))
* Arm the bootstrap-only override rule, and retire the documented pattern it refuses ([#80](https://github.com/bustanhq/bustan/issues/80))
* Follow-up: the singleton and durable caches are the last tables keyed by equality alone ([#81](https://github.com/bustanhq/bustan/issues/81))
* RF-05: APPLICATION resolves to four different types depending on entry path ([#82](https://github.com/bustanhq/bustan/issues/82))
* OL-02b: a module cannot declare two APP_GUARD entries, because the duplicate-token rule refuses them first ([#83](https://github.com/bustanhq/bustan/issues/83))
* Follow-up: the durable-controller refusal lives on the create_app path only, so a context accepts what an app refuses ([#88](https://github.com/bustanhq/bustan/issues/88))
* a missing body field is reported with a raw Python constructor TypeError ([#104](https://github.com/bustanhq/bustan/issues/104))
* the raw-response interceptor check does not see a component declared as two entries ([#110](https://github.com/bustanhq/bustan/issues/110))
* Two Annotated Inject markers naming equal tokens of different types collapse into one ([#115](https://github.com/bustanhq/bustan/issues/115))
* `bustan init` writes a tests package that shadows the source package, so two of its three tests cannot import ([#125](https://github.com/bustanhq/bustan/issues/125))
* a scaffolded project's controller test needs a test client that nothing installs or names ([#126](https://github.com/bustanhq/bustan/issues/126))
* the framework's own test surface still depended on a third-party test client ([#131](https://github.com/bustanhq/bustan/issues/131))
* the two adapters disagree about form bodies, and no capability declares it ([#135](https://github.com/bustanhq/bustan/issues/135))
* three supported surfaces still reach for the transport's test client ([#136](https://github.com/bustanhq/bustan/issues/136))
* `Application.close()` never stops the server, so a rolling deploy drops in-flight requests ([#151](https://github.com/bustanhq/bustan/issues/151))
* a per-route `@RateLimit` limits nothing, and three decorators do not say they are inert ([#155](https://github.com/bustanhq/bustan/issues/155))
* the pipeline is resolved from the container on every request, and a singleton can be built twice ([#156](https://github.com/bustanhq/bustan/issues/156))
* `ModuleRef` is always root-scoped, so a child module cannot resolve its own providers ([#158](https://github.com/bustanhq/bustan/issues/158))
* `bustan` without the `starlette` extra cannot compile a single route ([#170](https://github.com/bustanhq/bustan/issues/170))
* ten integration tests still import a third-party test client ([#178](https://github.com/bustanhq/bustan/issues/178))
* `AsgiTestClient` disconnects before the body is written, so a streamed response arrives empty and nothing raises ([#184](https://github.com/bustanhq/bustan/issues/184))
* the application the framework builds is not assignable to the framework's own `AsgiApp` port ([#186](https://github.com/bustanhq/bustan/issues/186))
* refusing one request evicts durable partitions other requests are still using ([#206](https://github.com/bustanhq/bustan/issues/206))
* the middleware failure path still builds the controller before the context, so it still answers 500 ([#207](https://github.com/bustanhq/bustan/issues/207))
* the ASGI adapter refuses an oversized body with 500, and the conformance matrix does not notice ([#212](https://github.com/bustanhq/bustan/issues/212))
* the conformance matrix reports every adapter answered identically when one member of one case is exempt ([#218](https://github.com/bustanhq/bustan/issues/218))
* a request-scope test compares `id()` across two requests, so address reuse fails it at random ([#219](https://github.com/bustanhq/bustan/issues/219))
* nothing bounds a multipart form on the Starlette adapter, and no conformance case sends one ([#223](https://github.com/bustanhq/bustan/issues/223))
* three scope tests assert identity by comparing `id()` across requests ([#225](https://github.com/bustanhq/bustan/issues/225))
* the body-binding messages report unexpected keys and no longer forward the interpreter's wording ([#239](https://github.com/bustanhq/bustan/issues/239))
* every example ships a test file with real assertions that nothing ever runs ([#162](https://github.com/bustanhq/bustan/issues/162))
* `@Cache`, `@Idempotent` and `@Audit` record a policy no runtime module reads, and now attach the interceptor that carries each of them out ([#216](https://github.com/bustanhq/bustan/issues/216))
* `enable_cors` is a public method that imports Starlette and works on one adapter ([#265](https://github.com/bustanhq/bustan/issues/265))
* a singleton that injects `ModuleRef` cannot be used in an HTTP application, because `create_app` does not push the application during startup ([#275](https://github.com/bustanhq/bustan/issues/275))
* a transport request annotation is matched by shape, so one adapter hands over the other adapter's request object - and never recognises its own ([#276](https://github.com/bustanhq/bustan/issues/276))
* a provider constructor annotating a foreign transport request type is still handed the wrong object ([#288](https://github.com/bustanhq/bustan/issues/288))
* a router 404 is plain text while every other error is problem details ([#304](https://github.com/bustanhq/bustan/issues/304))
* the two adapters answer the slash redirect with different shapes, and no conformance case covers it ([#328](https://github.com/bustanhq/bustan/issues/328))

### Architecture

* T-002 Honest quality gates and release hygiene ([#34](https://github.com/bustanhq/bustan/issues/34))
* T-104 Plan-then-execute kernel ([#58](https://github.com/bustanhq/bustan/issues/58))
* T-300: the contracts package ([#86](https://github.com/bustanhq/bustan/issues/86))
* eight packages still have no explicit `__all__` ([#89](https://github.com/bustanhq/bustan/issues/89))
* T-301: narrow the adapter port ([#90](https://github.com/bustanhq/bustan/issues/90))
* T-302: the proof adapter ([#91](https://github.com/bustanhq/bustan/issues/91))
* T-303: a conformance matrix that means something ([#92](https://github.com/bustanhq/bustan/issues/92))
* T-304: enforce the layering ([#93](https://github.com/bustanhq/bustan/issues/93))
* T-305: Starlette becomes an extra ([#94](https://github.com/bustanhq/bustan/issues/94))
* retype the request boundary against `HttpRequest`, so the kernel stops importing a web framework's type ([#96](https://github.com/bustanhq/bustan/issues/96))
* remove `AdapterRoute.registration`, the port escape hatch nothing produces any more ([#99](https://github.com/bustanhq/bustan/issues/99))
* move `token_identity` beside the markers so the rule has one copy ([#119](https://github.com/bustanhq/bustan/issues/119))
* `ResponsePlan` carries two fields that nothing ever writes ([#137](https://github.com/bustanhq/bustan/issues/137))
* the conformance suite certifies a lifespan it wrote itself, not the framework's ([#138](https://github.com/bustanhq/bustan/issues/138))
* T-306: the package layout move ([#139](https://github.com/bustanhq/bustan/issues/139))
* six extension points an enterprise must customise live in namespaces declared internal ([#159](https://github.com/bustanhq/bustan/issues/159))
* nothing holds the every-package-declares-`__all__` criterion ([#185](https://github.com/bustanhq/bustan/issues/185))
* the scaffolded module test is built on an internal namespace and does not type-check ([#187](https://github.com/bustanhq/bustan/issues/187))
* request limits are configured only through namespaces the stability guide declares internal ([#209](https://github.com/bustanhq/bustan/issues/209))
* split the public-surface assertions so two tickets adding exports cannot land in one file ([#229](https://github.com/bustanhq/bustan/issues/229))
* `ResponseSerializer` is on the supported surface with no supported way to install one ([#256](https://github.com/bustanhq/bustan/issues/256))
* the registry's three tables are assignable through `app.container` ([#257](https://github.com/bustanhq/bustan/issues/257))
* the runtime layer names two application types in four places ([#262](https://github.com/bustanhq/bustan/issues/262))
* the kernel reads controller metadata out of the runtime ([#263](https://github.com/bustanhq/bustan/issues/263))
* the adapter conformance suite sits in the runtime and assembles applications ([#264](https://github.com/bustanhq/bustan/issues/264))
* classify the health package and make the layering check blocking ([#266](https://github.com/bustanhq/bustan/issues/266))
* two CORS refusals raise stdlib types where the framework has its own ([#307](https://github.com/bustanhq/bustan/issues/307))
* declare providers as a tagged union of frozen value types ([#311](https://github.com/bustanhq/bustan/issues/311))
* refuse a dict where a provider is expected ([#312](https://github.com/bustanhq/bustan/issues/312))

### Operability

* The verification block dirties six example lockfiles on a clean checkout ([#54](https://github.com/bustanhq/bustan/issues/54))
* the published-package verification checks that scaffolded files exist, not that they work ([#128](https://github.com/bustanhq/bustan/issues/128))
* there is no health or readiness endpoint, so a pod is routed traffic before startup finishes ([#150](https://github.com/bustanhq/bustan/issues/150))
* the repository has no benchmark of any kind, so a performance regression is invisible ([#157](https://github.com/bustanhq/bustan/issues/157))
* the CLI has no diagnostics, no `--version`, and leaks tracebacks on a resolution error ([#160](https://github.com/bustanhq/bustan/issues/160))
* the release-gate command is wired to nothing, and the version story is told in five places ([#164](https://github.com/bustanhq/bustan/issues/164))
* the pre-commit hook regenerates the API reference and never stages it, so a docstring change fails CI ([#234](https://github.com/bustanhq/bustan/issues/234))
* the post-publish verification gives PyPI 65 seconds to propagate and then fails a good release ([#271](https://github.com/bustanhq/bustan/issues/271))
* `SECURITY.md` promises support for a pre-1.0 release that does not exist ([#279](https://github.com/bustanhq/bustan/issues/279))

### Documentation

* TROUBLESHOOTING.md gives the wrong fix for a module export, and covers no InvalidModuleError ([#52](https://github.com/bustanhq/bustan/issues/52))
* Follow-up: the scope documentation contradicts the rules the kernel now enforces ([#53](https://github.com/bustanhq/bustan/issues/53))
* Make the troubleshooting and scope documentation match the framework rc.1 actually ships ([#84](https://github.com/bustanhq/bustan/issues/84))
* document the two-entry spelling for global pipeline components ([#111](https://github.com/bustanhq/bustan/issues/111))
* every install instruction in the repository under-installs ([#134](https://github.com/bustanhq/bustan/issues/134))
* settle the records the layout move left behind ([#142](https://github.com/bustanhq/bustan/issues/142))
* six documents still describe the pre-T-306 package tree ([#143](https://github.com/bustanhq/bustan/issues/143))
* decide whether the audit evidence scripts are linted, and make the suppression consistent ([#145](https://github.com/bustanhq/bustan/issues/145))
* document exception filter precedence, which is not declaration order ([#147](https://github.com/bustanhq/bustan/issues/147))
* the scaffolded project's README tells the user to install without the extra ([#179](https://github.com/bustanhq/bustan/issues/179))
* a freshly scaffolded project is not formatted the way the framework formats itself ([#188](https://github.com/bustanhq/bustan/issues/188))
* nothing in the documentation says an application has request limits, or what its defaults are ([#210](https://github.com/bustanhq/bustan/issues/210))
* the troubleshooting guide's binding-error causes predate body type checking and no longer describe it ([#243](https://github.com/bustanhq/bustan/issues/243))
* the release checklist says the version lives in one place; it lives in seven, and following it produces a tag that fails ([#245](https://github.com/bustanhq/bustan/issues/245))
* the API reference generator renders a quoted forward reference verbatim, so tidying an annotation moves the reference and the suppression that hid it stays ([#32](https://github.com/bustanhq/bustan/issues/32))
* the behavioural documentation contradicts the code in three places, and waves 1 to 5 changed the rest ([#161](https://github.com/bustanhq/bustan/issues/161))
* a 1.x application will not start on 2.0 and there is no migration guide ([#163](https://github.com/bustanhq/bustan/issues/163))
* the versioning reference ties its stability promise to alpha releases, which 2.0.0 ends ([#281](https://github.com/bustanhq/bustan/issues/281))
* the request-scope guide limits the native-annotation refusal to handler parameters ([#291](https://github.com/bustanhq/bustan/issues/291))
* reorganise the documentation for diataxis and kebab-case names ([#309](https://github.com/bustanhq/bustan/issues/309))
* make uv the only supported manager and build out the tutorials ([#313](https://github.com/bustanhq/bustan/issues/313))
* retell the factory provider once the dict spelling is gone ([#316](https://github.com/bustanhq/bustan/issues/316))

## [1.1.0](https://github.com/bustanhq/bustan/compare/v1.0.1...v1.1.0) (2026-05-07)


### Features

* add native IoC kernel with provider tokens and provider definitions ([d7dd8fa](https://github.com/bustanhq/bustan/commit/d7dd8fa812a335e0613e61eb6c27c83275729593))
* expand framework core capabilities ([3cf36af](https://github.com/bustanhq/bustan/commit/3cf36af33d077089b606c4578d4d8c230a1a3b8e))
* expand framework core capabilities ([1659e7c](https://github.com/bustanhq/bustan/commit/1659e7c55ca16361e9830e1c1f02a0c6fbf1627c))
* implement Body, Query, Param, Header parameter decorators ([81b03dd](https://github.com/bustanhq/bustan/commit/81b03ddc89a24cf366164b5820d74331afc21f12))
* implement dynamic module support and update pre-commit hooks ([46fc5a4](https://github.com/bustanhq/bustan/commit/46fc5a4312bdbe4252e17c11200ed7c225c26823))
* implement NestJS-like application factory and async context hierarchy ([71db722](https://github.com/bustanhq/bustan/commit/71db72288ed2d0e85517be6413beb72e0518e291))
* replace dependency_injector internals with pure Python implementation ([a682713](https://github.com/bustanhq/bustan/commit/a682713a186f95bf16a3bb37c64e2fb3eecf350b))


### Bug Fixes

* CI failures - scaffold app.py rename, request-scoped controller example, API reference sync ([f99f2aa](https://github.com/bustanhq/bustan/commit/f99f2aa1994bb29c81e6cab5d6c55cf7af06de9d))
* **container:** keep local bindings authoritative over imported exports; fix root_key usage in ApplicationContext ([871f1f4](https://github.com/bustanhq/bustan/commit/871f1f463a71493b168b7c39eda4d10a5e8dddb3))
* detect version collisions for header/media-type versioning in compile_routes ([fcd7e49](https://github.com/bustanhq/bustan/commit/fcd7e49b68616dd45f8c51c40a7b5e2845a5aed4))
* lifecycle hooks, cookie binding, and Ip/HostParam alias handling ([862c626](https://github.com/bustanhq/bustan/commit/862c6267dc1c118012bf5f477764c18034051876))
* **scopes:** make get_singleton_lock thread-safe with a guard lock ([17209ba](https://github.com/bustanhq/bustan/commit/17209bae7ea2bec4a7b9504e7b52d7339721b650))


### Documentation

* reconcile public contract and versioning (P0) ([ab8157d](https://github.com/bustanhq/bustan/commit/ab8157d776ff6c8d8d01f821c5c6fbecf7a36ddd))
* reframe as agnostic ASGI architecture and implement Application properties (P0) ([83519b6](https://github.com/bustanhq/bustan/commit/83519b6036a9808776ea56c66c752f2587ecfa09))
* refresh api reference ([3191442](https://github.com/bustanhq/bustan/commit/319144263e14fe8e62b38001119783ee04ef2357))

## [1.0.1](https://github.com/bustanhq/bustan/compare/v1.0.0...v1.0.1) (2026-04-05)


### Bug Fixes

* **release:** use plural releases_created and update package name ([e196500](https://github.com/bustanhq/bustan/commit/e1965000f6d124ed2d2fe70927d7df251bd590d9))
* **release:** use plural releases_created and update package name ([70bcb08](https://github.com/bustanhq/bustan/commit/70bcb087bcb27cb49963cf2fae95054d1eb3e986))

## [1.0.0](https://github.com/bustanhq/bustan/compare/v0.1.0...v1.0.0) (2026-04-05)


### ⚠ BREAKING CHANGES

* All public decorators are now PascalCase. Existing snake_case names are no longer supported.

### Features

* prepare open source adoption baseline ([03ec783](https://github.com/bustanhq/bustan/commit/03ec7835fac2954fff3c1ba7349cb9935851c172))


### Bug Fixes

* unblock release-please pull request creation ([2127063](https://github.com/bustanhq/bustan/commit/21270638b813c1838c7b5a5c09e181261a799f53))
* unblock release-please pull request creation ([d84986f](https://github.com/bustanhq/bustan/commit/d84986f5367e34b7c8c24def8d2b92b09dfcf79d))


### Documentation

* update contact and support email addresses ([236d2c8](https://github.com/bustanhq/bustan/commit/236d2c8152932e02757f30eb61ff4851006e6160))


### Code Refactoring

* rename public decorators to PascalCase ([9cd6e00](https://github.com/bustanhq/bustan/commit/9cd6e00ab14f935110de7e9dc1bfe35eb2252ce9))

## [0.1.0](https://github.com/bustanhq/bustan/compare/v0.0.1...v0.1.0) (2026-04-04)


### Features

* prepare open source adoption baseline ([03ec783](https://github.com/bustanhq/bustan/commit/03ec7835fac2954fff3c1ba7349cb9935851c172))


### Bug Fixes

* unblock release-please pull request creation ([2127063](https://github.com/bustanhq/bustan/commit/21270638b813c1838c7b5a5c09e181261a799f53))
* unblock release-please pull request creation ([d84986f](https://github.com/bustanhq/bustan/commit/d84986f5367e34b7c8c24def8d2b92b09dfcf79d))
