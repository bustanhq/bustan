# Changelog

> [!IMPORTANT]
> Versions `1.0.0` and `1.0.1` were unintentionally released during CI/CD setup. Treat them as early alpha orphans. The first production-ready, non-alpha release target remains `2.0.0`.

## [2.0.0-rc.5](https://github.com/bustanhq/bustan/compare/v2.0.0rc4...v2.0.0rc5) (2026-09-08)

The candidate that closes the audit. Every defect the September dependency-injection audit
demonstrated is now fixed and held there by the script that used to reproduce it, and the CI job
that runs those scripts stopped being advisory: it is a regression gate, and a finding that comes
back fails the build rather than appearing in a summary nobody reads.

The rest of the candidate is what an application built on this framework needs from it that had no
answer before. A route's pipeline is resolved once instead of once per request. The framework can
be measured, and a regression in what it costs fails CI. Five extension points an enterprise must
customise reached the supported surface, and the surface now derives from a written policy rather
than drifting alongside one. The command-line tool can answer questions about the application in
front of it.

**This candidate carries two breaking changes**, both to `ModuleRef` and both stated in full on the
commit that made them:

* A `ModuleRef` injected into a provider or a controller now names the module that class was
  declared in, not the root module. A reference asked of the application directly still names the
  root. Code reading `ModuleRef.module_key`, or relying on an injected reference resolving through
  the root, sees a different module.
* `strict=False` now widens a token its own module cannot see into a search of every module in the
  application, and refuses to choose when more than one declares it, naming `for_module()` as the
  way to say which. It previously fell back to what the root module could see, which widened
  nothing. A lookup that used to return a root-visible provider may now return a different one or
  raise.

Not a breaking change, and worth knowing: a mapping written where a factory's `inject` token
belongs is now refused while the module is compiled, naming the module, the token and the entry.
It previously reached the visibility lookup as `TypeError: unhashable type: 'dict'`. And a dynamic
registration may now replace a provider its base module declares rather than colliding with it.

`INQUIRER` yields the requesting class rather than the requesting instance. That is documented in
[COMPARISONS.md](docs/explanation/comparisons.md) as a deliberate difference from NestJS: this framework injects
through the constructor only, so at the moment the token is answered the consumer's `__init__` has
not run and no instance of it exists.

Every entry below is a closed issue from the 2.0.0-rc.5 milestone, grouped by the classification
label it carries. All six are listed; two carry `follow-up` as well and appear under their
classification.

### Correctness

* the pipeline is resolved from the container on every request, and a singleton can be built twice ([#156](https://github.com/bustanhq/bustan/issues/156))
* `ModuleRef` is always root-scoped, so a child module cannot resolve its own providers ([#158](https://github.com/bustanhq/bustan/issues/158))
* refusing one request evicts durable partitions other requests are still using ([#206](https://github.com/bustanhq/bustan/issues/206))

### Architecture

* six extension points an enterprise must customise live in namespaces declared internal ([#159](https://github.com/bustanhq/bustan/issues/159))

### Operability

* the repository has no benchmark of any kind, so a performance regression is invisible ([#157](https://github.com/bustanhq/bustan/issues/157))
* the CLI has no diagnostics, no `--version`, and leaks tracebacks on a resolution error ([#160](https://github.com/bustanhq/bustan/issues/160))

## [2.0.0-rc.4](https://github.com/bustanhq/bustan/compare/v2.0.0rc3...v2.0.0rc4) (2026-09-08)

The request contract and operability. A request now has one error contract from the edge to
the handler and back, an exception hierarchy that reaches every common status without naming
internals in a refusal, finite limits on what one request may spend, health and readiness a
scheduler can route on, a shutdown that drains rather than drops, observability that measures
what a request cost and can be correlated across services, and a throttler that counts what a
deployment actually served.

The candidate also closes the last of the request-binding gaps: a handler is no longer handed
a value whose type contradicts its own annotation.

**This candidate carries six breaking changes.** Each is stated in full on the commit that
made it; in brief:

* A request body whose field values do not match their declared types is answered `400`
  rather than passed to the handler, and a nested object arrives as the type its field
  declares rather than as a plain mapping.
* Every application now serves under finite request limits. A body over one megabyte, an
  upload over ten, more than twenty parts bound to one parameter, or a request running longer
  than thirty seconds is refused where it previously was not. `bustan.adapters.asgi` no longer
  exports `RequestBodyTooLarge`, and an oversized body is answered `413` rather than `500`.
* `bustan.errors` exports nineteen new names. A request refused for want of an identity is
  answered `401` with a `WWW-Authenticate` header where it was answered `403`, and an
  application whose authenticated route cannot see an authenticator registry is refused at
  build time.
* `RequestTracer` and `TraceSpan` are reshaped to OpenTelemetry's span model.
  `MetricsSink.record_request` gains a `duration_seconds` keyword, and a sink written without
  it is still called with the labels alone rather than broken. `Logger` emits structured JSON
  through the standard library rather than a formatted line through `print()`.
* `ThrottlerStorage` declares one asynchronous `count_request(key, ttl, limit)` in place of
  `increment` and `get_ttl`. An implementation of the old protocol must be rewritten.
* `Application.close()` stops a running server, drains it and waits for its port to be
  released, where before it ran the lifecycle teardown alone and left the server serving.
  Shutdown hooks receive the name of the signal that stopped the process.

Not a breaking change, and stated here because it changes what a reader should expect:
`Cache`, `Idempotent` and `Audit` now say in their own docstrings that nothing in the
request path acts on them. All three still accept every argument and still record their
policy on the route's compiled plan, exactly as they did in `2.0.0-rc.3`. What changed is
that the absence is stated where a reader meets it - the first line of each docstring,
which is what an editor's hover shows - together with what to do instead until the
behaviour lands.

Every entry below is a closed issue from the 2.0.0-rc.4 milestone, grouped by the
classification label it carries. All 26 are listed. Fourteen carry two classification labels;
each appears once, under the more severe of them.

### Security

* a body field is never checked against its declared type, so a handler is handed an int that is a str ([#103](https://github.com/bustanhq/bustan/issues/103))
* constructor failures bypass every filter, and a rejected request still pays for its providers ([#148](https://github.com/bustanhq/bustan/issues/148))
* only four HTTP statuses are reachable, and the 403 body leaks internal role names ([#149](https://github.com/bustanhq/bustan/issues/149))
* no body-size limit, no upload cap and no timeout, so one large POST is an out-of-memory vector ([#152](https://github.com/bustanhq/bustan/issues/152))
* request duration is never measured, and a user-supplied newline forges log records ([#153](https://github.com/bustanhq/bustan/issues/153))
* the throttler multiplies its limit by worker count and shares one bucket behind a load balancer ([#154](https://github.com/bustanhq/bustan/issues/154))
* a body that declares no length is read in full on the default adapter before the limit refuses it ([#211](https://github.com/bustanhq/bustan/issues/211))
* the ASGI adapter reads a body 4096 times the application's limit before anything refuses it ([#217](https://github.com/bustanhq/bustan/issues/217))

### Correctness

* a missing body field is reported with a raw Python constructor TypeError ([#104](https://github.com/bustanhq/bustan/issues/104))
* `Application.close()` never stops the server, so a rolling deploy drops in-flight requests ([#151](https://github.com/bustanhq/bustan/issues/151))
* a per-route `@RateLimit` limits nothing, and three decorators do not say they are inert ([#155](https://github.com/bustanhq/bustan/issues/155))
* the middleware failure path still builds the controller before the context, so it still answers 500 ([#207](https://github.com/bustanhq/bustan/issues/207))
* the ASGI adapter refuses an oversized body with 500, and the conformance matrix does not notice ([#212](https://github.com/bustanhq/bustan/issues/212))
* the conformance matrix reports every adapter answered identically when one member of one case is exempt ([#218](https://github.com/bustanhq/bustan/issues/218))
* a request-scope test compares `id()` across two requests, so address reuse fails it at random ([#219](https://github.com/bustanhq/bustan/issues/219))
* nothing bounds a multipart form on the Starlette adapter, and no conformance case sends one ([#223](https://github.com/bustanhq/bustan/issues/223))
* three scope tests assert identity by comparing `id()` across requests ([#225](https://github.com/bustanhq/bustan/issues/225))
* the body-binding messages report unexpected keys and no longer forward the interpreter's wording ([#239](https://github.com/bustanhq/bustan/issues/239))

### Architecture

* nothing holds the every-package-declares-`__all__` criterion ([#185](https://github.com/bustanhq/bustan/issues/185))
* request limits are configured only through namespaces the stability guide declares internal ([#209](https://github.com/bustanhq/bustan/issues/209))
* split the public-surface assertions so two tickets adding exports cannot land in one file ([#229](https://github.com/bustanhq/bustan/issues/229))

### Operability

* there is no health or readiness endpoint, so a pod is routed traffic before startup finishes ([#150](https://github.com/bustanhq/bustan/issues/150))
* the pre-commit hook regenerates the API reference and never stages it, so a docstring change fails CI ([#234](https://github.com/bustanhq/bustan/issues/234))

### Documentation

* nothing in the documentation says an application has request limits, or what its defaults are ([#210](https://github.com/bustanhq/bustan/issues/210))
* the troubleshooting guide's binding-error causes predate body type checking and no longer describe it ([#243](https://github.com/bustanhq/bustan/issues/243))
* the release checklist says the version lives in one place; it lives in seven, and following it produces a tag that fails ([#245](https://github.com/bustanhq/bustan/issues/245))

## [2.0.0-rc.3](https://github.com/bustanhq/bustan/compare/v2.0.0rc2...v2.0.0rc3) (2026-09-07)

Ports and adapters. The transport becomes replaceable rather than assumed: a contracts
package, a narrowed adapter port, a second adapter written against the ASGI specification
and the standard library alone, a conformance matrix that holds both adapters to the same
answers, an enforced layering rule, Starlette demoted to an optional extra, and the package
layout move the rest of the wave was gated behind.

The candidate also closes a defect shipped in `2.0.0rc2`: without the `starlette` extra
installed, the framework could not compile a single route.

Every entry below is a closed issue from the 2.0.0-rc.3 milestone, grouped by the
classification label it carries. All 34 are listed. One, [#121](https://github.com/bustanhq/bustan/issues/121), carries both `security`
and `operability`; it appears once, under Security.

### Security

* audit the resolved dependency set of the root project and all six examples in CI, from their committed lockfiles, so an advisory is found before a release rather than after one ([#121](https://github.com/bustanhq/bustan/issues/121))

### Correctness

* the raw-response interceptor check does not see a component declared as two entries ([#110](https://github.com/bustanhq/bustan/issues/110))
* `bustan init` writes a tests package that shadows the source package, so two of its three tests cannot import ([#125](https://github.com/bustanhq/bustan/issues/125))
* a scaffolded project's controller test needs a test client that nothing installs or names ([#126](https://github.com/bustanhq/bustan/issues/126))
* the framework's own test surface still depended on a third-party test client ([#131](https://github.com/bustanhq/bustan/issues/131))
* the two adapters disagree about form bodies, and no capability declares it ([#135](https://github.com/bustanhq/bustan/issues/135))
* three supported surfaces still reach for the transport's test client ([#136](https://github.com/bustanhq/bustan/issues/136))
* `bustan` without the `starlette` extra cannot compile a single route ([#170](https://github.com/bustanhq/bustan/issues/170))
* ten integration tests still import a third-party test client ([#178](https://github.com/bustanhq/bustan/issues/178))
* `AsgiTestClient` disconnects before the body is written, so a streamed response arrives empty and nothing raises ([#184](https://github.com/bustanhq/bustan/issues/184))
* the application the framework builds is not assignable to the framework's own `AsgiApp` port ([#186](https://github.com/bustanhq/bustan/issues/186))

### Architecture

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
* the scaffolded module test is built on an internal namespace and does not type-check ([#187](https://github.com/bustanhq/bustan/issues/187))

### Documentation

* document the two-entry spelling for global pipeline components ([#111](https://github.com/bustanhq/bustan/issues/111))
* every install instruction in the repository under-installs ([#134](https://github.com/bustanhq/bustan/issues/134))
* settle the records the layout move left behind ([#142](https://github.com/bustanhq/bustan/issues/142))
* six documents still describe the pre-T-306 package tree ([#143](https://github.com/bustanhq/bustan/issues/143))
* decide whether the audit evidence scripts are linted, and make the suppression consistent ([#145](https://github.com/bustanhq/bustan/issues/145))
* document exception filter precedence, which is not declaration order ([#147](https://github.com/bustanhq/bustan/issues/147))
* the scaffolded project's README tells the user to install without the extra ([#179](https://github.com/bustanhq/bustan/issues/179))
* a freshly scaffolded project is not formatted the way the framework formats itself ([#188](https://github.com/bustanhq/bustan/issues/188))

### Operability

* the published-package verification checks that scaffolded files exist, not that they work ([#128](https://github.com/bustanhq/bustan/issues/128))

## [2.0.0-rc.2](https://github.com/bustanhq/bustan/compare/v1.1.0...v2.0.0rc2) (2026-09-06)

The first release candidate published from `main`. It carries the whole of the 2.0.0-rc.1 and
2.0.0-rc.2 milestones: rc.1 emptied without ever being tagged, so its work ships here rather
than in a release of its own.

Every entry below is a closed milestone issue, grouped by the classification label it carries.
Three are not listed: the two epics that group the waves, and one report closed as a duplicate
of another in the same milestone.

> [!NOTE]
> `1.1.1` was published on 2026-09-04 from a branch that was never merged to `main`, and no
> changelog entry or version bump followed it. The four fixes it carried were ported into `main`
> under [#62](https://github.com/bustanhq/bustan/issues/62), listed under rc.1 below, so this release supersedes it. `main`'s
> version files read `1.1.0` until this release; they now read `2.0.0rc2`.

### 2.0.0-rc.2 - the resolution kernel's remaining defects (15 issues)

#### Security

* EX-04: a 403 body names the guard's dotted class path and the auth strategy, with debug off ([#65](https://github.com/bustanhq/bustan/issues/65))

#### Correctness

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
* Two Annotated Inject markers naming equal tokens of different types collapse into one ([#115](https://github.com/bustanhq/bustan/issues/115))

### 2.0.0-rc.1 - foundation and the plan-then-execute kernel (19 issues)

#### Security

* T-103 Effective scope algebra ([#45](https://github.com/bustanhq/bustan/issues/45))
* 2.0.0 would ship without four fixes that 1.1.1 already has: CR-01, RI-02, RI-05, RI-12 ([#62](https://github.com/bustanhq/bustan/issues/62))
* RI-10: a durable-scoped controller with no context-key hook is served as one instance to every tenant ([#64](https://github.com/bustanhq/bustan/issues/64))

#### Correctness

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

#### Architecture

* T-002 Honest quality gates and release hygiene ([#34](https://github.com/bustanhq/bustan/issues/34))
* T-104 Plan-then-execute kernel ([#58](https://github.com/bustanhq/bustan/issues/58))

#### Documentation

* TROUBLESHOOTING.md gives the wrong fix for a module export, and covers no InvalidModuleError ([#52](https://github.com/bustanhq/bustan/issues/52))
* Follow-up: the scope documentation contradicts the rules the kernel now enforces ([#53](https://github.com/bustanhq/bustan/issues/53))
* Make the troubleshooting and scope documentation match the framework rc.1 actually ships ([#84](https://github.com/bustanhq/bustan/issues/84))

#### Operability

* The verification block dirties six example lockfiles on a clean checkout ([#54](https://github.com/bustanhq/bustan/issues/54))

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
