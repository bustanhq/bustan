# Bustan DI and IoC Container: Adversarial Audit

| | |
| --- | --- |
| Target | `bustan` 1.1.0 (PyPI), `main` at commit `0cfe6dc` (2026-08-16) |
| Audited | `src/bustan/core/ioc`, `src/bustan/core/module`, `src/bustan/core/lifecycle`, `src/bustan/app`, `src/bustan/addons`, `src/bustan/testing`, `src/bustan/common/decorators/injectable.py`, and the container's consumers in `src/bustan/platform/http` and `src/bustan/pipeline` |
| Date | 2026-09-04 |
| Findings | 91 (1 critical, 15 high, 39 medium, 32 low, 4 info); 82 confirmed by executed scripts, 4 measured, 5 verified by reading |
| Evidence | `repros/` (standardized regression harness) and `repros/evidence/` (verbatim verification scripts) |

## 1. Executive summary

The container is small, readable and well tested for the paths the tests
exercise, but its request-isolation model is not enforced where it matters
most. The documented rule "singleton controllers must not depend on
request-scoped providers" is stated in three places and enforced in none:
a default-scope controller that injects a request-scoped provider, the
`Request`, or the `Response` is built once on the first request and serves
that caller's identity, headers and response object to every later caller
(RI-01). Four more high-severity variants reach the same outcome through
`use_class` dicts that silently drop the class's declared scope (RI-02),
durable providers pinned by singleton owners (RI-03) or holding a stranger's
`Request` (RI-04), and `RESPONSE` injection with no scope guard (RI-05).
Every one of these is reachable by an unauthenticated HTTP client against
an application written the way the documentation and NestJS habits suggest.

The second theme is silent misbinding. An undecorated subclass of an
`@Injectable` class registers its parent instead of itself (PN-01); a
constructor annotation is rebound to any visible provider class with the same
bare name (RF-01); `X | None` is treated as an opaque token and `OptionalDep`
injects `None` while the dependency is registered (RF-02); re-exporting an
imported provider passes graph validation and fails at first request (MG-01);
and provider overrides never reach dependents that were already built, so a
test can believe it swapped a database while the real one keeps serving
(OL-01, OL-02). None of these raise where the mistake is made.

The third theme is that the container validates too little at bootstrap and
too much lazily. Only singleton bindings are instantiated at startup; every
transient and request-scoped provider and every controller is first resolved
on a live request, so a missing dependency deploys as a 500 (MG-04). The
same lifespan-versus-lazy split masks several scope defects: they fail
loudly with a misleading message when the lifespan runs and leak when it
does not (RI-06, RI-07).

Resource behavior is the fourth theme: durable instances and their locks are
never evicted and are keyed by whatever the provider derives from the request,
so a client varying one header grows process memory without bound (CR-01);
the sync and async resolution paths use different locks and can build the
same singleton twice (CR-02); and constructor planning re-runs reflection and
an O(visible tokens) namespace synthesis on every request (CR-05).

The test suite deserves its own sentence: coverage is gated at 95 percent
but the gate rounds 94.53 up and passes (QA-11), six tests assert the
defective behaviors above as contracts (QA-12), and the resolver is tested
through private seams rather than public behavior (QA-14).

Finally, the code carries real maintenance debt: a 931-line, tab-indented
resolver with eight near-duplicate sync and async method pairs that have
already drifted (QA-02, QA-03), two disagreeing implementations of the
visibility rule (MG-03), core modules importing the HTTP platform and
Starlette types directly (QA-01), stringly typed bindings and `Any` at the
public boundary (QA-05), and `bustan.testing` re-implementing lifecycle
orchestration and drifting from it (OL-03).

Before a production-ready 2.0 the maintainers should: close the five
request-isolation holes with one effective-scope rule applied at container
build time; move dependency validation to bootstrap for all scopes; fix the
annotation resolution order; bound or evict durable state; make overrides
either bootstrap-only or dependency-aware; and collapse the resolver's twin
code paths. Section 6 sequences that work; the `repros/` harness turns each
finding into a regression check that flips from `REPRODUCED` to `FIXED`.

## 2. Scope, method and baseline

### 2.1 What was audited

The dependency-injection kernel and everything that feeds or consumes it:

- `core/ioc`: `Container`, `Registry` and `normalize_provider`, `ScopeManager`,
  `OverrideManager`, `Resolver`, tokens.
- `core/module`: `@Module`, `@Global`, `DynamicModule`, the compiler, the
  graph builder and export validation, `ConfigurableModuleBuilder`.
- `core/lifecycle`: hook protocols, `LifecycleManager`, the stage runner.
- `app`: `ApplicationContext`, `Application`, bootstrap, the Starlette lifespan.
- `addons`: `ModuleRef`, `DiscoveryService`, context ids.
- `testing`: `override_provider`, `create_test_app`, `TestingModuleBuilder`.
- Consumers: `ControllerFactory`, `execute_http_route`, the route compiler's
  global pipeline providers, `PolicyGuard`'s authenticator lookup.

HTTP parameter binding, routing, OpenAPI, CORS and throttling were out of
scope except where they touch the container.

### 2.2 Method

The audit was adversarial and evidence-driven:

1. A baseline run of the project's own checks (tests, ruff, ty, coverage).
2. A lead-auditor read of every in-scope file, producing 19 hypotheses that
   were each turned into a runnable script before being believed.
3. Eight independent finder passes, each with a different lens (request
   isolation, concurrency and resource growth, module graph, provider
   normalization, constructor reflection, overrides and lifecycle, code
   quality, documentation and NestJS parity), each required to prove claims
   by running code. They produced 108 raw findings.
4. Consolidation of duplicates into 70 unique root causes (91 after the later passes).
5. A verification pass in which a separate reproducer wrote and executed a
   script per finding and recorded a verdict, a severity calibration and the
   decisive output; 48 findings were confirmed this way and none refuted.
   A skeptic pass ran for the first five findings only (a usage limit
   interrupted it); the lead auditor reviewed the rest by hand and executed
   spot checks for ten of the unscripted claims (nine held, one sub-claim did
   not, see QA-08).
6. Two further finder passes (test-suite audit, multi-tenant attacker) and a
   completeness critic ran against the established list; their 21 additions
   went through the same reproducer verification and are marked "round two"
   or "critic round" in section 4.

Severity follows one guide throughout: critical means a cross-request data
leak or authorization bypass reachable by an HTTP client; high means wrong
behavior of a documented feature, resource exhaustion, or silent misbinding;
medium means a footgun or documentation drift a normal user will hit; low
means a smell with maintenance cost; info is an observation.

Status values: Confirmed means an executed script demonstrated the behavior
(the script is in `repros/` or `repros/evidence/`); Measured means the claim
is a metric that was computed; Verified by reading means the claim is a
design or documentation statement checked against the cited lines but not
executable.

### 2.3 Baseline

| Check | Result |
| --- | --- |
| `uv run pytest` | 397 passed in 2.4 s |
| `uv run ruff check .` | clean (default rule set only: E4, E7, E9, F) |
| `uv run ty check src tests scripts` | clean |
| `uv run ruff format --check src` | 40 of 94 files would be reformatted; `resolver.py` is tab-indented |
| Branch coverage, `bustan.core.ioc` | resolver 92 percent, scopes 92, overrides 96, container 99, registry 100 |
| Branch coverage, `bustan.core.lifecycle` | hooks 79 percent, manager 90, runner 90 |
| Branch coverage, `bustan.core.module` | graph 94 percent, rest 100 |
| Configuration | `[tool.uv.workspace] members = ["mini"]` names a directory that does not exist |

Toolchain: Python 3.13.12 via uv, starlette 1.0.0, anyio 4.13, pydantic 2.13.

## 3. Findings at a glance

Ids are grouped by area so that later additions append without renumbering:
RI request isolation, CR concurrency and resources, MG module graph, PN
provider definitions, RF constructor reflection, OL overrides and lifecycle,
QA code quality and architecture, DP documentation and parity, EX request
execution order and error contract. The Repro
column names the regression script in `repros/` when one exists and the
verbatim evidence script in `repros/evidence/` otherwise.

### 3.1 Request isolation and scope leaks

| Id | Severity | Status | Title | Repro |
| --- | --- | --- | --- | --- |
| RI-01 | critical | Confirmed | Default-scope controllers capture the first request's identity, `Request` and `Response` | `singleton_controller_captures_request_state.py`, `evidence/RI-01.py` |
| RI-02 | high | Confirmed | `use_class` dicts drop the class's declared scope; `use_value` and `use_existing` ignore an explicit scope | `dict_provider_silently_downgrades_declared_scope.py`, `evidence/RI-02.py` |
| RI-03 | high | Confirmed | Singleton owners may capture a tenant-keyed durable instance and serve it to every tenant | `evidence/RI-03.py` |
| RI-04 | high | Confirmed | Durable providers receive and retain the first caller's `Request` for the life of the partition | `evidence/RI-04.py` |
| RI-05 | high | Confirmed | `RESPONSE` injection has no owner-scope guard; later header and status writes are lost | `evidence/RI-05.py` |
| RI-06 | medium | Confirmed | Factory `inject` lists and `use_existing` aliases bypass the scope guard; misleading startup error with lifespan, leak without | `factory_inject_and_use_existing_bypass_scope_guard.py`, `evidence/RI-06.py` |
| RI-07 | medium | Confirmed | Nested `resolve(request=None)` inherits the outer request, so singletons can pull request state imperatively | `evidence/RI-07.py` |
| RI-08 | medium | Confirmed | `INQUIRER` in a singleton records the first inquirer; startup success depends on declaration order | `evidence/RI-08.py` |
| RI-09 | medium | Confirmed | `_detect_owner_scope` picks the first binding for a class, so scope inference depends on registration order | `evidence/RI-09.py` |
| RI-10 | medium | Confirmed | `@Controller(scope=DURABLE)` is accepted and silently downgraded to a singleton | `evidence/RI-10.py` |
| RI-11 | high | Confirmed | Request-scoped and durable providers are constructed before any guard runs; anonymous requests populate partitions and stall the loop | `evidence/RI-11.py` |
| RI-12 | high | Confirmed | `request_context_id` is `id()`-based and collides across sequential requests | `evidence/RI-12.py` |
| RI-13 | medium | Confirmed | Route middleware runs outside the request-scope lifetime; a second instance is built after `call_next` | `evidence/RI-13.py` |
| RI-14 | low | Confirmed | Transient providers cannot receive `Request` even under a request-scoped controller | `evidence/RI-14.py` |

### 3.2 Concurrency, locking and resource growth

| Id | Severity | Status | Title | Repro |
| --- | --- | --- | --- | --- |
| CR-01 | high | Confirmed | Durable instances and their locks grow without bound under client-controlled keys; no eviction | `durable_cache_grows_without_bound.py`, `evidence/CR-01.py` |
| CR-02 | low | Confirmed | Sync and async resolution use different locks; a singleton can be built twice and the loser leaks | `sync_and_async_resolve_double_construct_singleton.py`, `evidence/CR-02.py` |
| CR-03 | low | Confirmed | Construction runs on the event-loop thread under `threading.Lock`; a slow constructor in a worker stalls the loop | `evidence/CR-03.py` |
| CR-04 | low | Confirmed | Request-scoped cache writes are unlocked; concurrent resolution in one request builds two instances | `evidence/CR-04.py` |
| CR-05 | medium | Confirmed | Constructor planning re-runs reflection and O(visible tokens) namespace synthesis on every instantiation | `evidence/CR-05.py` |
| CR-06 | low | Confirmed | `get_durable_context_key` is called three to four times per resolve; unstable or unhashable keys misbehave | `evidence/CR-06.py` |

### 3.3 Module graph and visibility

| Id | Severity | Status | Title | Repro |
| --- | --- | --- | --- | --- |
| MG-01 | high | Confirmed | Re-exporting an imported provider passes validation and fails at runtime with "Binding not found" | `reexported_provider_not_resolvable.py`, `evidence/MG-01.py` |
| MG-02 | medium | Confirmed | Colliding exports from global modules or imports resolve first-wins by traversal order, silently | `duplicate_global_exports_import_order_dependent.py`, `evidence/MG-02.py` |
| MG-03 | medium | Confirmed | Visibility is computed twice (graph and registry) and the two disagree in both directions | `evidence/MG-03.py` |
| MG-04 | medium | Confirmed | Dependencies of transient and request-scoped providers and of controllers are never validated at bootstrap | `missing_dependency_only_fails_at_request_time.py`, `evidence/MG-04.py` |
| MG-05 | medium | Confirmed | `DynamicModule` identity is `id()`-based: equal registrations create duplicate instances; ids shift with order | `evidence/MG-05.py` |
| MG-06 | medium | Confirmed | Module classes are instantiated twice with no arguments; a parameterized `__init__` fails with a raw `TypeError` | `evidence/MG-06.py` |
| MG-07 | low | Confirmed | Exporting a module class (NestJS re-export) fails with a provider error and wrong troubleshooting advice | lead spot check |
| MG-08 | low | Confirmed | A `DynamicModule` cannot override a token its base module declares | lead spot check |
| MG-09 | low | Confirmed | Cycle detection through a `DynamicModule` reports no path; the key-collision guard is dead code | - |
| MG-10 | low | Confirmed | `@Module` accepts sets and a bare dict; double decoration overwrites silently | lead spot check |

### 3.4 Provider definitions, metadata and tokens

| Id | Severity | Status | Title | Repro |
| --- | --- | --- | --- | --- |
| PN-01 | high | Confirmed | `@Injectable` metadata is inherited: registering an undecorated subclass binds the parent; pipeline resolution too | `injectable_metadata_inherited_by_subclass.py`, `evidence/PN-01.py` |
| PN-02 | high | Confirmed | A singleton whose value is `None` is never cached; an async `None` factory makes `init()` fail | `none_valued_singleton_rebuilt_every_resolve.py`, `evidence/PN-02.py` |
| PN-03 | medium | Confirmed | Overrides match tokens by identity while the registry matches by equality; runtime-built tokens cannot be overridden | `evidence/PN-03.py` |
| PN-04 | medium | Confirmed | Dict normalization ignores `inject` on `use_class`, silently prefers the first `use_*` key, explodes a string `inject` | `evidence/PN-04.py` |
| PN-05 | medium | Confirmed | A registered but undecorated pipeline class is built with no arguments and returns 500 on every request | `evidence/PN-05.py` |
| PN-06 | low | Confirmed | Invalid dict input escapes as raw `TypeError` or `ValueError` instead of `InvalidProviderError` | `unhashable_token_raises_raw_typeerror.py`, `evidence/PN-06.py` |
| PN-07 | low | Verified by reading | Provider metadata is a mutable dict on the class, trusted verbatim at graph-build time | - |
| PN-08 | info | Verified by reading | `InjectionToken` equality is identity-based and undocumented; same-named tokens are indistinguishable in errors | - |
| PN-09 | medium | Confirmed | Factory `inject` lists cannot name `REQUEST`, `RESPONSE`, `APPLICATION` or `INQUIRER` | `evidence/PN-09.py` |
| PN-10 | low | Confirmed | Durable scope accepts factory targets that can never supply a key; an instance-method key hook raises a raw `TypeError` | `evidence/PN-10.py` |
| PN-11 | low | Confirmed | `StrEnum` tokens silently alias bare strings; overrides then target the wrong binding | `evidence/PN-11.py` |

### 3.5 Constructor reflection and annotation resolution

| Id | Severity | Status | Title | Repro |
| --- | --- | --- | --- | --- |
| RF-01 | high | Confirmed | A visible provider with the same bare name silently hijacks a string annotation | `same_name_class_hijacks_annotation.py`, `evidence/RF-01.py` |
| RF-02 | high | Confirmed | `Optional[X]` and `X \| None` are opaque tokens; `OptionalDep` injects `None` although `X` is registered | `defaults_and_optional_unions_not_honored.py`, `evidence/RF-02.py` |
| RF-03 | medium | Confirmed | An inherited `__init__` has its string annotations evaluated in the subclass module's globals | `inherited_init_annotations_wrong_namespace.py`, `evidence/RF-03.py` |
| RF-04 | medium | Confirmed | Constructor defaults are ignored; `OptionalDep` substitutes `None` for the declared default | `defaults_and_optional_unions_not_honored.py`, `evidence/RF-04.py` |
| RF-05 | medium | Confirmed | `APPLICATION` resolves to three different types depending on the entry path | `application_token_resolves_to_three_types.py`, `evidence/RF-05.py` |
| RF-06 | medium | Confirmed | `APPLICATION` is unavailable during lifespan startup, so any singleton that injects it breaks eager instantiation | `evidence/RF-06.py` |
| RF-07 | low | Confirmed | The `APPLICATION` fallback uses `hasattr(request, "app")`, which leaks Starlette's `KeyError` | `evidence/RF-07.py` |
| RF-08 | low | Confirmed | Classes that customize `__new__` and keep `object.__init__` bypass injection with a raw `TypeError` | `evidence/RF-08.py` |
| RF-09 | low | Confirmed | Multiple `Inject` markers on one parameter are accepted; the last wins silently | lead spot check |
| RF-10 | medium | Confirmed | `ModuleRef` and `DiscoveryService` cannot be resolved from `ApplicationContext` (raw `TypeError`) | `evidence/RF-10.py` |
| RF-11 | low | Confirmed | Introspection edge cases: C-implemented `__init__`, malformed annotations, non-`self` first parameter, `OptionalDep` on special tokens | `evidence/RF-11.py` |

### 3.6 Overrides, testing surface and lifecycle

| Id | Severity | Status | Title | Repro |
| --- | --- | --- | --- | --- |
| OL-01 | high | Confirmed | Overrides never reach already-built dependents; fakes built during an override outlive it | `override_leaves_dependents_stale.py`, `evidence/OL-01.py` |
| OL-02 | high | Confirmed | `APP_*` providers are baked at compile time: overrides are a silent no-op, one per module, never request-scoped | `app_guard_cannot_be_request_scoped_one_per_module.py`, `evidence/OL-02.py` |
| OL-03 | high | Confirmed | `bustan.testing` re-implements lifecycle orchestration and has drifted from `LifecycleManager` | `evidence/OL-03.py` |
| OL-04 | medium | Confirmed | Lifecycle hooks are duck-typed onto every cached singleton, including `use_value` objects and mocks | `lifecycle_hooks_duck_typed_on_value_providers.py`, `evidence/OL-04.py` |
| OL-05 | medium | Confirmed | A startup failure after `on_module_init` runs no teardown and leaves `LifecycleState` unset | `evidence/OL-05.py` |
| OL-06 | medium | Confirmed | Overrides cannot target `DynamicModule` registrations through `module_cls`; the error names a nonexistent kwarg | `evidence/OL-06.py` |
| OL-07 | medium | Confirmed | Overridden providers receive no lifecycle hooks | `evidence/OL-07.py` |
| OL-08 | medium | Confirmed | `TestingModuleBuilder` builds replacements from the root module, so they cannot see the replaced provider's dependencies | `evidence/OL-08.py` |
| OL-09 | medium | Confirmed | Async factories work for singleton scope only; request and transient async factories return 500 | `evidence/OL-09.py` |
| OL-10 | medium | Confirmed | Three inconsistent "is this factory async" predicates leak un-awaited coroutines | `evidence/OL-10.py` |
| OL-11 | medium | Confirmed | No public way to resolve request-scoped providers from handler or guard code | `module_ref_cannot_reach_request_scope_in_handler.py`, `evidence/OL-11.py` |
| OL-12 | low | Confirmed | Durable instances are excluded from warm-up and from every lifecycle stage | lead spot check |
| OL-13 | low | Confirmed | Shutdown leaves caches populated and startup is one-shot; a second `TestClient` block fails | lead spot check |
| OL-14 | low | Confirmed | The aggregated shutdown `LifecycleError` discards the individual exceptions | lead spot check |
| OL-15 | info | Confirmed | Provider hook order mixes leaf-first async warm-up with root-first sync instantiation | lead spot check |
| OL-16 | info | Confirmed | The lifecycle `signal` argument is documented but never supplied | `evidence/OL-16.py` |

### 3.7 Code quality, architecture and typing

| Id | Severity | Status | Title | Repro |
| --- | --- | --- | --- | --- |
| QA-01 | medium | Confirmed | Layering violations: core imports the HTTP platform and Starlette; `HttpRequest` is not injectable | `evidence/QA-01.py` |
| QA-02 | medium | Measured | The resolver is an 846-line class with eight near-duplicate sync and async pairs that have drifted | `evidence/QA-02.py` |
| QA-03 | low | Measured | Formatting and lint are not enforced: tab-indented resolver, 40 unformatted files, default rule set only | - |
| QA-04 | low | Verified by reading | Stale narrative comments, dead branches, redundant exception chaining, misleading docstrings | - |
| QA-05 | low | Confirmed | Typing debt: `Any` and `object` at the public boundary; `InjectionToken[T]` never drives inference | - |
| QA-06 | low | Confirmed | Container internals are public mutable dicts reachable through `app.container` | - |
| QA-07 | low | Verified by reading | `ModuleKey` is a raw union, duck-typed through `hasattr` probes | - |
| QA-08 | low | Measured | Tooling drift: dangling workspace member, global `fail_under` breaks targeted runs, `uv run` rewrites the lock | - |
| QA-09 | low | Confirmed | Test gaps: the async resolver path, scope detection, global pipeline providers and every scope-leak edge are untested | - |
| QA-10 | info | Confirmed | `ContextVar`s are created per container instance; ambient state is invisible across containers | lead spot check |
| QA-11 | medium | Confirmed | The coverage gate is nominal: 94.53 percent prints FAIL and exits 0 | `evidence/QA-11.py` |
| QA-12 | medium | Confirmed | The suite pins known-defective behaviors as contracts | `evidence/QA-12.py` |
| QA-13 | medium | Confirmed | Provider hook failure paths and lifecycle re-entrancy are untested | `evidence/QA-13.py` |
| QA-14 | medium | Confirmed | The resolver is tested through private seams on hand-built registries | `evidence/QA-14.py` |
| QA-15 | medium | Confirmed | Override-by-scope, durable-over-HTTP and dynamic-module overrides are untested | `evidence/QA-15.py` |
| QA-16 | low | Verified by reading | Tautological tests and 13 copies of a request fixture | `evidence/QA-16.py` |

### 3.8 Documentation drift and NestJS parity

| Id | Severity | Status | Title | Repro |
| --- | --- | --- | --- | --- |
| DP-01 | medium | Confirmed | `ModuleRef` injected through DI is always root-scoped; `strict=False` is not a container-wide lookup | `evidence/DP-01.py` |
| DP-02 | low | Confirmed | `for_root_async` and `register_async` cannot see the importing module's providers (no `imports`) | lead spot check |
| DP-03 | low | Confirmed | Smaller parity gaps: `INQUIRER` is a class, dict `inject` entries crash, no `forwardRef`, no property injection, no lazy modules | - |

### 3.9 Request execution order and error contract

| Id | Severity | Status | Title | Repro |
| --- | --- | --- | --- | --- |
| EX-01 | medium | Confirmed | Exceptions while building the controller or its providers bypass filters, `APP_FILTER` and observability | `evidence/EX-01.py` |
| EX-02 | medium | Confirmed | A broken `AUTHENTICATOR_REGISTRY` wiring is reported as 403 on every request | `evidence/EX-02.py` |
| EX-03 | low | Confirmed | The middleware exception path is unguarded; `debug=True` sends a DI traceback to the client | `evidence/EX-03.py` |
| EX-04 | low | Confirmed | 403 responses disclose guard class paths and strategy names | `evidence/EX-04.py` |

Documentation statements contradicted by behavior are listed with the
finding that contradicts them: RI-01 (`docs/REQUEST_SCOPED_PROVIDERS.md:33`
and `:113`, `docs/TROUBLESHOOTING.md:26`), OL-05 (`docs/LIFECYCLE.md:88`),
OL-11 (the `ApplicationContext.get` docstring and `docs/API_REFERENCE.md`),
CR-04 ("one cached instance per request"), OL-15 (`docs/LIFECYCLE.md:30`),
MG-07 (`docs/TROUBLESHOOTING.md:11`), RI-13 (`docs/REQUEST_SCOPED_PROVIDERS.md:24`),
RI-11 (`docs/REQUEST_SCOPED_PROVIDERS.md:87`), OL-16 (`docs/LIFECYCLE.md:9`).

## 4. Detailed findings

Each entry gives the mechanism as read from the code, the decisive output of
the script that demonstrated it, the impact, and a proposed fix. Line numbers
refer to commit `0cfe6dc`.

### 4.1 Request isolation and scope leaks

#### RI-01 Default-scope controllers capture the first request's identity, Request and Response

Severity: critical. Category: security. Status: Confirmed (three finders, lead auditor, reproducer).

Where: `src/bustan/core/ioc/resolver.py:697` (the scope guard returns early when
`owner_is_controller`), `resolver.py:730-734` (`allow_request_runtime` is true for
every controller, so `Request` is handed over), `resolver.py:745-748` (`RESPONSE`
has no owner check at all), `resolver.py:515` (`owner_is_controller` is derived
from class identity only), `src/bustan/platform/http/controller_factory.py:49-76`
(`@Controller(scope=...)` is read but never passed to the resolver as
`binding_scope`; the singleton instance is cached in `controller_singletons`),
`docs/REQUEST_SCOPED_PROVIDERS.md:33` and `:113`, `docs/TROUBLESHOOTING.md:26`.

Mechanism: the guard that stops singletons from depending on request-scoped
providers exempts every controller regardless of the controller's own scope,
and the special-token path gives any controller the live `Request` and
`Response`. Controllers are singletons by default and are built lazily on the
first request, so the first caller's `RequestIdentity`, `Request` (headers,
cookies, ASGI scope) and `Response` placeholder are cached for the process
lifetime. The documentation states the opposite rule and promises a
`ProviderResolutionError`. Eager startup never touches controllers, so the
lifespan does not catch it.

Evidence: `repros/singleton_controller_captures_request_state.py`:

```
RESULT: RI-01a REPRODUCED - /me/ answered 'alice' then 'alice'; bob saw alice
RESULT: RI-01b REPRODUCED - /raw/ answered 'alice' then 'alice'; bob saw alice
```

`repros/evidence/RI-01.py` additionally shows the same `request_id` and
`response_id` on both requests. A skeptic pass confirmed that no test locks in
the permissive behavior: dropping the exemption and running the suite passes.

Impact: any application written the way the docs and NestJS habits suggest (a
controller that injects an authenticated principal, tenant context or the
request) serves the first caller's identity to everyone after it. This is an
authentication bypass and cross-tenant disclosure reachable by an
unauthenticated HTTP client.

Fix: pass `ControllerMetadata.scope` into `instantiate_class` as
`binding_scope`; remove the `owner_is_controller` exemptions at
`resolver.py:697` and `:730`, so only request and transient owners inside a
request-scoped chain may receive request-scoped providers, `Request` or
`Response`; validate controller constructors at `compile_route_contracts` time
so a singleton controller naming `Request`, `REQUEST`, `RESPONSE` or a
request-scoped binding fails at `create_app`; add a two-request integration
test with different identity headers.

#### RI-02 use_class dicts drop the class's declared scope; use_value and use_existing ignore an explicit scope

Severity: high. Category: correctness with security impact. Status: Confirmed (six finders).

Where: `src/bustan/core/ioc/registry.py:29-34` (class metadata is read only for
bare class entries), `registry.py:44` (dict scope defaults to singleton without
consulting `use_class`), `registry.py:62-69` (`use_value` hard-codes singleton),
`registry.py:71-77` (`use_existing` hard-codes transient),
`src/bustan/common/decorators/injectable.py:45-53`.

Mechanism: `{"provide": Iface, "use_class": Cls}` never looks at
`Cls.__bustan_provider__["scope"]`. A class decorated
`@Injectable(scope="request")` bound under an interface token, the standard
NestJS idiom, becomes a process-wide singleton. Because the binding is singleton
the request-scope guard never fires either. A `scope` key given with
`use_value` or `use_existing` is discarded without error, and an invalid scope
string raises a raw `ValueError` rather than `InvalidProviderError`.

Evidence: `repros/dict_provider_silently_downgrades_declared_scope.py`
prints `class declares scope=request but the binding is singleton`;
`repros/evidence/RI-02.py` shows the HTTP consequence with the lifespan
running: `alice -> {'events': ['secret-of-alice']}` then
`bob -> {'events': ['secret-of-alice', 'secret-of-bob']}` from the same instance.

Impact: per-request mutable state declared on the class is shared across
requests and users, silently.

Fix: in `normalize_provider` default the `use_class` scope from the class
metadata when the dict omits `scope`; raise `InvalidProviderError` when an
explicit dict scope is less strict than the class scope, when `scope`
accompanies `use_value` or `use_existing`, and when the scope string is
invalid. Document the precedence rule.

#### RI-03 Singleton owners may capture a tenant-keyed durable instance and serve it to every tenant

Severity: high. Category: security. Status: Confirmed.

Where: `src/bustan/core/ioc/resolver.py:693-698` (the guard tests only
`dependency_binding.scope is ProviderScope.REQUEST`), `resolver.py:203` and
`:866` (durable key derived from the active request),
`src/bustan/core/lifecycle/runner.py:85` (eager pass resolves singletons with no
request, so a durable dependency is built under the `get_durable_context_key(None)`
partition).

Mechanism: durable bindings pass the guard, so a singleton provider or a
default-scope controller takes a durable dependency, resolves it once under
the first caller's durable key, and keeps that tenant's instance forever. With
the lifespan, eager startup pins the no-request partition; if the durable
provider also injects `Request`, startup aborts with an error about `Request`
availability that hides the design problem.

Evidence: `repros/evidence/RI-03.py`: `[A controller] tenant-a -> {'tenant':
'tenant-a', 'cfg_id': 1402...}` then `[A controller] tenant-b -> {'tenant':
'tenant-a', 'cfg_id': 1402...}`; provider variants with and without lifespan
reproduce the same sharing.

Impact: cross-tenant disclosure whenever durable scope is used for tenant
partitioning, which is its canonical use.

Fix: extend the guard to reject durable dependencies for singleton owners
(providers and controllers) with an error naming both scopes, and enforce the
same rule at container build time so it does not depend on request order.

#### RI-04 Durable providers receive and retain the first caller's Request

Severity: high. Category: security. Status: Confirmed (three finders).

Where: `src/bustan/core/ioc/resolver.py:730` (`allow_request_runtime` includes
`is_durable_scoped`), `resolver.py:732-734`, `src/bustan/core/ioc/scopes.py:37`
and `:84-85` (durable instances retained indefinitely).

Mechanism: a durable class may take `Request`, but the instance is cached per
durable key and reused by every request and user that shares the key. Each
later user receives an object holding a stranger's `Request`, including the
`Authorization` header, cookies and the ASGI `receive` closure; those request
objects keep their scopes alive for the process lifetime.

Evidence: `repros/evidence/RI-04.py`: `bob -> {'first_user': 'alice',
'auth_in_retained_request': 'Bearer alice-token', ...}`; after 200 more
distinct tenants, `retained Request objects: 201`.

Impact: credential and header disclosure between users sharing a durable key,
plus retention of every first request per partition.

Fix: remove `is_durable_scoped` from `allow_request_runtime`; give durable
providers the durable key (or a small payload object) instead of the request;
document that durable instances outlive the request and are shared by every
caller with the same key.

#### RI-05 RESPONSE injection has no owner-scope guard

Severity: high. Category: correctness. Status: Confirmed.

Where: `src/bustan/core/ioc/resolver.py:745-748`,
`src/bustan/platform/http/execution.py:113-114` (a fresh placeholder `Response`
per request) and the merge step later in the same function.

Mechanism: the `RESPONSE` branch returns the active response to any owner.
`execute_http_route` merges only the current request's placeholder into the
final response, so a singleton controller, a lazily built singleton provider,
or a transient owned by a singleton keeps request one's placeholder and every
later header, cookie or status write goes to an object nobody reads.

Evidence: `repros/evidence/RI-05.py`: request 1 `status=201 x-seen-by='req-1'
x-count='1'`, requests 2 and 3 `status=200 x-seen-by=None x-count=None`, same
`response_id` throughout. The request-scoped control behaves correctly.

Impact: `Set-Cookie`, status codes and headers silently missing for every
client after the first; unlike RI-06 this reproduces with the lifespan running.

Fix: gate the `RESPONSE` branch with the same owner-scope rule as `REQUEST`
(after RI-01) and document `RESPONSE` as per-request only.

#### RI-06 Factory inject lists and use_existing aliases bypass the scope guard

Severity: medium. Category: security. Status: Confirmed (three finders, lead auditor).

Where: `src/bustan/core/ioc/resolver.py:371-395` (`call_factory` resolves
`inject` tokens with a plain `resolve` and no guard), `resolver.py:397-424`
(async twin), `src/bustan/core/ioc/registry.py:71-77` (`use_existing` is always
transient, which is what the guard inspects), `resolver.py:671-703`.

Mechanism: the guard inspects only the direct dependency's binding and only
for class constructors. A singleton factory whose `inject` list names a
request-scoped token, or a singleton class that depends on a `use_existing`
alias of a request-scoped token, is built during the first request and
cached. With the lifespan running, eager instantiation happens with no request
and fails with `Request-scoped provider ... requires an active request`, which
names the wrong problem. Without the lifespan (a `TestClient` used without a
`with` block, `uvicorn --lifespan off`, `create_app_context` without `init`)
the leak is silent.

Evidence: `repros/factory_inject_and_use_existing_bypass_scope_guard.py`:

```
RESULT: RI-06a REPRODUCED - startup failed with a misleading error: Request-scoped provider ... requires an active request
RESULT: RI-06b REPRODUCED - factory path served alice to bob
RESULT: RI-06c REPRODUCED - alias path served alice to bob
```

Impact: cross-request identity leak in every setting that skips the
lifespan, which includes most test suites; a wrong diagnostic in production.

Fix: compute an effective scope per binding at container build time
(`use_existing` inherits its target's scope; a factory's scope must be at
least as strict as every `inject` token's scope) and reject singleton or
durable owners that reach request scope with the documented guard error,
independent of the lifespan.

#### RI-07 Nested resolve(request=None) inherits the outer request

Severity: medium. Category: security. Status: Confirmed.

Where: `src/bustan/core/ioc/scopes.py:101-104` (`push_request(None)` leaves the
`ContextVar` untouched), `src/bustan/core/ioc/resolver.py:113`,
`src/bustan/app/application.py:53-62` (`ApplicationContext.get` passes no
request and documents itself as non-request-scoped),
`src/bustan/addons/module_ref.py:48`.

Mechanism: a provider constructor that calls `app.get(RequestIdentity)` or
`ModuleRef.get(...)` while an outer resolution has a request active sees that
request and builds request-scoped providers. The guard only inspects declared
constructor parameters, so a singleton pulling request state imperatively is
never rejected and caches the first request's data.

Evidence: `repros/evidence/RI-07.py`: `[A] no lifespan: alice -> {'owner':
'alice'} | bob -> {'owner': 'alice'}`; `[C] with request pushed,
container.resolve(RequestIdentity, request=None) -> alice`.

Impact: same class of leak as RI-06, masked by the lifespan in the same way.

Fix: make `ApplicationContext.get` and `ModuleRef.get` clear the active
request (push an explicit sentinel) or require a request argument; track the
innermost owner scope under construction and refuse request-scoped resolution
when it is singleton or durable.

#### RI-08 INQUIRER in a singleton records the first inquirer; startup depends on declaration order

Severity: medium. Category: correctness. Status: Confirmed (two finders).

Where: `src/bustan/core/ioc/resolver.py:770-779` (`INQUIRER` read from
`construction_stack[-2]` with no owner-scope check), `resolver.py:387`
(`call_factory` pushes no construction frame),
`src/bustan/core/lifecycle/runner.py:83-87` (eager pass resolves singletons at
top level in binding order), `docs/API_REFERENCE.md:697`.

Mechanism: a singleton that injects `INQUIRER` is built once for whichever
dependent asks first and then shared, so every later dependent sees the wrong
inquirer. Listing the provider before its consumers builds it at top level and
aborts startup with `only available during nested provider resolution`;
listing it after succeeds. Classes built through a factory `inject` list see
the factory's consumer.

Evidence: `repros/evidence/RI-08.py`: `singleton Logger: Billing sees Billing |
Shipping sees Billing | same Logger instance: True`; `providers=[Logger,
ServiceA] init() -> ProviderResolutionError`; `providers=[ServiceA, Logger]
init() -> ok`.

Impact: silently wrong attribution in any logging or audit provider modelled
on the NestJS `INQUIRER` idiom with the default scope; order-dependent startup.

Fix: reject or auto-promote to transient any class binding whose constructor
injects `INQUIRER` under singleton or durable scope; skip such bindings in
eager instantiation; push a construction frame in `call_factory`; document
that `INQUIRER` is the requesting class and transient-only.

#### RI-09 _detect_owner_scope picks the first binding for a class

Severity: medium. Category: correctness. Status: Confirmed (three finders).

Where: `src/bustan/core/ioc/resolver.py:607-614`, `resolver.py:516-520`,
`src/bustan/core/ioc/container.py:96`, `src/bustan/addons/module_ref.py:54`,
`src/bustan/testing/builder.py:151`.

Mechanism: every `instantiate_class` caller (`ControllerFactory`,
`ModuleRef.create`, `TestingModuleBuilder.use_class`, `Container.instantiate_class`)
omits `binding_scope`, so the resolver scans all bindings and takes the first
class binding targeting the class regardless of the requesting module. The
same class bound with different scopes in two modules gets whichever was
registered first, and that feeds both `allow_request_runtime` and the guard.

Evidence: `repros/evidence/RI-09.py`: with `imports=[ReqFirstModule,
SingletonModule]` instantiation succeeds and injects the request; with the
order reversed it raises `depends on request-scoped provider`.

Impact: scope inference and `Request` injection permission change with import
order; nothing in the test suite executes these lines.

Fix: require callers to pass the owner scope (controller metadata scope, an
explicit argument for `ModuleRef.create` and `use_class`); restrict the scan to
bindings visible from the requesting module and raise when they disagree.

#### RI-10 @Controller(scope=DURABLE) is accepted and silently downgraded to a singleton

Severity: medium. Category: correctness. Status: Confirmed (round two).

Where: `src/bustan/common/decorators/controller.py:27` (any `ProviderScope`
member is accepted), `src/bustan/platform/http/controller_factory.py:52-76`
(only transient and request are handled; everything else falls through to the
singleton cache), `src/bustan/platform/http/scanner.py:128-131` (a public
`get_durable_context_key` on a controller is rejected as a handler without a
route decorator).

Evidence: `repros/evidence/RI-10.py`: requests with `x-tenant` a, b, a all
report `controller_instance: 1`; `controller_singletons: ['DC']`,
`durable_instances: []`.

Impact: a controller meant to be partitioned per tenant is shared by every
tenant with no error; nothing documents durable controllers, so this is a
silent-acceptance bug rather than a documented-contract breach.

Fix: reject durable scope in the `Controller` decorator with
`InvalidControllerError`, or implement it in `ControllerFactory.instantiate`;
either way replace the fall-through with an explicit `else: raise` and add a
factory test parametrized over every scope member.

#### RI-11 Request-scoped and durable providers are constructed before any guard runs

Severity: high. Category: security. Status: Confirmed (round two, two finders).

Where: `src/bustan/platform/http/execution.py:122` (controller and its
request-scoped dependencies), `:140` (pipeline components including
request-scoped guards) and `:147` (`run_guards`), `src/bustan/pipeline/guards.py:45`
(`PolicyGuard` writes `request.state.principal` only inside `can_activate`),
`src/bustan/core/ioc/resolver.py:203` and `:861-886` (durable key derived from
the request and the instance cached before authentication).

Mechanism: construction precedes authentication. A request-scoped provider
that reads `request.state.principal` in its constructor sees `None` even on
an `@Auth` route and is cached for the request; `get_durable_context_key`
runs with no principal, so durable partitions can only be keyed by
unauthenticated client input; an anonymous request rejected with 403 has
already executed the request-scoped and durable constructors and left the
partition it named in `durable_instances`; and because durable construction
takes a `threading.Lock` and runs inline on the event loop, each anonymous
request with a fresh key forces a full constructor run on the loop before it
is rejected.

Evidence: `repros/evidence/RI-11.py`: authenticated request `ctor_saw_principal:
False` while `state_principal_after_guard: True`; anonymous 403 leaves
`durable partitions: ['acme', 'victim-corp']`; `after 500 anonymous requests:
partitions 502 locks 502`; five concurrent anonymous requests with a 0.2 s
durable constructor raised an unrelated `/ping` from 0.0024 s to 0.811 s.

Impact: the documented recommendation to keep the authenticated principal in a
request-scoped provider cannot be met through constructor injection when
`PolicyGuard` is the authenticator; unauthenticated clients can populate
tenant partitions and convert constructor latency into loop stalls for every
tenant (this combines with CR-01 and CR-03).

Fix: run guards before constructing request-scoped and durable dependencies
(resolve guards first, or defer controller and provider construction until
after `run_guards`) and document the ordering; pass an authenticated context
to `get_durable_context_key` or add a post-authentication key hook; evict
partitions created by a request that ends in a guard rejection; construct
shared-scope providers off the loop thread or through the async path.

#### RI-12 request_context_id is id()-based and collides across sequential requests

Severity: high. Category: correctness. Status: Confirmed (round two).

Where: `src/bustan/addons/context.py:29` (`str(id(request))`), `context.py:16`
("Stable scope-qualified context identifier"), `src/bustan/__init__.py:81`
(exported from the top-level package), `src/bustan/core/ioc/resolver.py:838-841`
(the resolver's own comment explains why durable caches must never be keyed
on `id(request)`).

Evidence: `repros/evidence/RI-12.py`: 200 sequential requests from distinct
users produced 37 distinct ids; 27 ids were handed to more than one user; one
id served five users.

Impact: any consumer that keys a process-lifetime structure on the value
(audit trail, idempotency key, lock table) mixes requests from different
users; the public helper does exactly what the kernel forbids.

Fix: generate the id once per request (`uuid4` or a monotonic counter) and
store it on `request.state`; document it as unique per request rather than
per live object.

#### RI-13 Route middleware runs outside the request-scope lifetime

Severity: medium. Category: correctness. Status: Confirmed (round two).

Where: `src/bustan/platform/http/adapters/starlette.py:99-106` (middleware
resolved and awaited around the route), `src/bustan/platform/http/execution.py:212`
(request-scope caches cleared inside `execute_http_route`'s `finally`),
`execution.py:114` (the `Response` context is pushed only after the middleware
phase has begun), `docs/REQUEST_SCOPED_PROVIDERS.md:24-26`.

Evidence: `repros/evidence/RI-13.py`: `Ident constructions during one request:
['Ident(u2)#...708544', 'Ident(u2)#...358288']`, `audit events visible after
call_next: 0`; a request-scoped middleware injecting `Response` returns 500.

Impact: a middleware that resolves a request-scoped provider after
`call_next` (to flush an audit trail, for example) gets a fresh empty
instance, silently dropping request-local state and contradicting the
one-instance-per-request promise.

Fix: clear request-scope state at the outermost boundary (the endpoint wrapper
after the middleware chain returns) and push the `Response` and application
contexts before the chain starts; document that middleware shares the request
scope.

#### RI-14 Transient providers cannot receive Request even under a request-scoped controller

Severity: low. Category: parity gap. Status: Confirmed (round two).

Where: `src/bustan/core/ioc/resolver.py:730` (`allow_request_runtime` excludes
transient owners), `resolver.py:740-742`.

Evidence: `repros/evidence/RI-14.py`: `create_app` succeeds; every `GET /t/`
returns 500 with `requests framework-owned type Request, which is not
available in provider DI` in the log; the same helper declared request-scoped
works.

Fix: allow `Request` injection for transient owners resolved inside a request
(NestJS promotes such providers implicitly), or reject the configuration at
bootstrap; document the rule.

### 4.2 Concurrency, locking and resource growth

#### CR-01 Durable instances and their locks grow without bound under client-controlled keys

Severity: high. Category: resource exhaustion. Status: Confirmed (three finders, lead auditor).

Where: `src/bustan/core/ioc/scopes.py:37-39` (`durable_instances`,
`durable_locks`, `async_construction_locks`), `scopes.py:84-99` (entries are
only ever added), `scopes.py:158` (the only clearing methods are for controller
singletons and request state), `src/bustan/core/ioc/resolver.py:827-846`.

Mechanism: one instance and one `threading.Lock` (plus one `anyio.Lock` on the
async path) per distinct durable key, retained for the process lifetime. The
key is whatever `get_durable_context_key(request)` returns; every example
derives it from a header. No size cap, TTL, weak reference, eviction API or
disposal hook exists, and shutdown does not clear the tables.

Evidence: `repros/durable_cache_grows_without_bound.py`: `2000 durable
instances and 2000 locks retained`; `repros/evidence/CR-01.py` measures about
9.5 MB of traced growth for 2000 keys with a 1 KB payload and confirms the
tables survive lifespan shutdown.

Impact: an unauthenticated client varying one header allocates memory
linearly in request count until the process dies.

Fix: add `evict_durable(key)` and `clear_durable()` on `ScopeManager` exposed
through `Container`; drop per-key locks once construction completes; support
an optional bounded LRU or TTL policy with an `on_module_destroy` callback on
eviction; document that durable keys must be bounded and derived from
authenticated identity.

#### CR-02 Sync and async resolution use different locks; a singleton can be built twice

Severity: low (reproducer calibration; the lead auditor rates it medium for durable providers). Category: concurrency. Status: Confirmed.

Where: `src/bustan/core/ioc/resolver.py:139-149` and `:194-212` (sync path,
`threading.Lock`), `resolver.py:214-227` and `:255-266` (async path,
`anyio.Lock`), `resolver.py:903-911` (`_cache_instance` discards the loser).

Mechanism: the two lock families are independent, so a worker-thread sync
resolution and an event-loop async resolution can both find the cache empty
and construct. The loser is dropped with no lifecycle hook, so anything it
opened leaks, and the double-check acquires a `threading.Lock` on the loop
thread. Real mixing exists: `_warm_async_factories` uses `resolve_async` while
request-time paths use `resolve`.

Evidence: `repros/sync_and_async_resolve_double_construct_singleton.py`:
`singleton constructed 2 times`; `repros/evidence/CR-02.py`: `FakeConn objects
still open: 2`, `max event-loop heartbeat gap: 0.950 s`.

Impact: leaked connections for durable providers or for apps run without the
lifespan; an event-loop stall while the async caller waits.

Fix: one construction-state machine per key (a per-key lock plus an in-flight
marker or event the async path awaits without blocking the loop); at minimum
run `on_module_destroy` or warn when `_cache_instance` discards a fresh
instance.

#### CR-03 DI construction runs on the event-loop thread under threading locks

Severity: low. Category: concurrency. Status: Confirmed.

Where: `src/bustan/platform/http/execution.py:122` (synchronous
`factory.instantiate` inside the async route), `execution.py:164` (sync
handlers run in worker threads), `src/bustan/core/ioc/resolver.py:143-147`,
`src/bustan/core/ioc/scopes.py:87`.

Mechanism: nested construction does `with lock:` on `threading.Lock`s and runs
user constructors while holding them. If a worker thread is inside a slow
constructor for an uncached key (typical for durable providers, which are
never eagerly built), a concurrent loop-thread resolution of the same key
blocks and freezes every other request.

Evidence: `repros/evidence/CR-03.py`: `loop-thread resolve() blocked 0.800 s;
max event-loop heartbeat gap 0.808 s`; end to end, `/ping` took 0.603 s
while a worker held the lock.

Fix: make the request-time path async (`resolve_async` and
`instantiate_class_async` from `execute_http_route`) with anyio locks and
offload blocking constructors to a thread; document that constructors must
not block.

#### CR-04 Request-scoped cache writes are unlocked

Severity: low. Category: concurrency. Status: Confirmed.

Where: `src/bustan/core/ioc/resolver.py:151-152` and `:268-269` (construction
outside any lock), `resolver.py:883-888` (unconditional store),
`src/bustan/platform/http/controller_factory.py:55-63`.

Mechanism: for request scope both paths construct outside a lock and write
the cache without check-and-set, unlike the singleton and durable branches.
User concurrency inside one request (a task group in an async handler, threads
sharing a request) or an async factory yielding at an await builds two
instances, contradicting the documented "one cached instance per request".

Evidence: `repros/evidence/CR-04.py`: `sync threads, one request: Identity
built=2 distinct returned=2`; `async tasks, one request: AsyncIdentity built=2`;
the singleton control stays at 1.

Fix: `dict.setdefault` and return the winner in `_cache_instance`, or a
per-request lock stored on `request.state`.

#### CR-05 Constructor planning re-runs reflection on every instantiation

Severity: medium. Category: design debt with a performance cost. Status: Confirmed and measured.

Where: `src/bustan/core/ioc/resolver.py:509-604` (`_plan_constructor_parameters`
has no cache), `resolver.py:540-547` (`get_type_hints` with a freshly built
namespace), `resolver.py:803-825` (`_build_type_hint_namespace` loops over all
controllers and every visible token), `resolver.py:607` (linear scan of all
bindings when `binding_scope` is `None`).

Mechanism: the plan is a pure function of `(class, module_key, binding_scope)`
and the registry is immutable after build, yet it is recomputed for every
transient or request-scoped instantiation and for every request-scoped
controller.

Evidence: `repros/evidence/CR-05.py`: two `inspect.signature`, two
`get_type_hints` and two namespace builds per instantiation of a request-scoped
controller with four dependencies; 194 us per instantiation at 31 visible
tokens and 596 us at 1501; `_build_type_hint_namespace` is 79 percent of
planning time. The lead auditor's independent measurement showed 32 us at 10
tokens growing to 127 us at 1000.

Fix: memoize the planned parameters per `(class, module_key, binding_scope)`
and precompute the per-module namespace in `Container._build_bindings`. The
same plan is the natural place for the bootstrap validation in MG-04.

#### CR-06 get_durable_context_key is called three to four times per resolve

Severity: low. Category: correctness. Status: Confirmed.

Where: `src/bustan/core/ioc/resolver.py:127`, `:144`, `:203`, `:223`,
`:827-846`, `:866`, `:892`.

Mechanism: the user classmethod is invoked independently from the cache
probe, the lock lookup and the store, so a key that is not perfectly stable
within one resolution makes lookup, lock and store disagree; hashability is
never validated.

Evidence: `repros/evidence/CR-06.py`: `sync: key calls on uncached resolve =
3`, `async: 4`; a counter-valued key yields a distinct instance and a new
cache entry per resolve; a list key raises a raw `TypeError`.

Fix: compute the key once at the top of `resolve` and `resolve_async`,
validate it with `collections.abc.Hashable`, and pass it through the helpers.

### 4.3 Module graph and visibility

#### MG-01 Re-exporting an imported provider passes validation and fails at runtime

Severity: high. Category: correctness. Status: Confirmed (two finders, lead auditor).

Where: `src/bustan/core/module/graph.py:214-221` (`_validate_exports` accepts
any imported token as exportable), `src/bustan/core/ioc/container.py:54-59`
(imported exports are mapped to the importing module key) and `:42` (global
exports to the global module's own key), `src/bustan/core/ioc/resolver.py:122-125`
(`get_binding((re-exporter, token))` is `None`, so `Binding not found`).

Mechanism: the graph records which tokens a module exports but not where they
are declared. The container assumes the exporting module owns the binding.
For a facade module that imports `DataModule` and re-exports `Repository`, the
importer's visibility maps `Repository` to the facade, which has no binding.
Startup resolves only each module's own bindings, so nothing fails until the
first request. An existing test locks in graph acceptance of this shape without
resolving through it.

Evidence: `repros/reexported_provider_not_resolvable.py`: `graph accepted the
re-export but resolve failed: ... Binding not found`; `repros/evidence/MG-01.py`
shows `GET /deep/ -> 500` for both the two-hop and the `@Global` facade case.

Impact: the standard NestJS facade pattern boots cleanly and returns 500 on
first use with a message that does not mention re-exports.

Fix: carry the declaring module with every export (token to origin `ModuleKey`,
computed in `ensure_node` by following imported nodes) and copy the origin
into the registry's visibility; or reject re-exports in `_validate_exports`
until they are supported. Add a bootstrap check that every visibility entry
has a binding.

#### MG-02 Colliding exports resolve first-wins by traversal order, silently

Severity: medium. Category: correctness. Status: Confirmed (two finders, lead auditor).

Where: `src/bustan/core/ioc/container.py:42` (`setdefault` for global exports),
`container.py:54-59` (`if token not in accessible` for imports), `container.py:61-63`
(globals appended last), `src/bustan/core/ioc/overrides.py:64-70` (the override
manager detects the same ambiguity and refuses).

Mechanism: the winner is whichever module appears first in pre-order traversal
or import order; global exports lose to any import. No error, warning or log.
`override_provider` on the same graph raises `registered in multiple modules`,
so the app serves what the test harness refuses to override.

Evidence: `repros/duplicate_global_exports_import_order_dependent.py`:
`imports=[G1,G2] -> from-G1, imports=[G2,G1] -> from-G2, no error`.
`repros/evidence/MG-02.py` adds the two-imports case and the per-consumer
divergence (`ConsumerImportsA sees from-A; ConsumerImportsNothing sees from-G1`).

Fix: raise `InvalidModuleError` when two global modules, or two imports not
shadowed by a local binding, export the same token; document the precedence
(local, then imports in order, then global) if shadowing is intended.

#### MG-03 Visibility is computed twice and the two implementations disagree

Severity: medium. Category: design debt. Status: Confirmed (two finders).

Where: `src/bustan/core/module/graph.py:175-184` (`available_providers` is
local bindings plus direct imported exports), `graph.py:214` (`_validate_exports`
uses the graph view), `src/bustan/core/ioc/container.py:37-63` (the registry
recomputes the rule and adds global exports), `src/bustan/core/ioc/resolver.py:915`
(the resolver reads only the registry).

Mechanism: a globally exported token is resolvable but absent from the
documented `available_providers_for`; a module cannot export a globally visible
token it can resolve; a re-exported token is present in both views but
unresolvable (MG-01).

Evidence: `repros/evidence/MG-03.py`: `graph.available_providers_for(Consumer)
has GlobalSvc = False` while `container.resolve(GlobalSvc, module=Consumer)
works = True`; `Facade exports GlobalSvc ... ExportViolationError`.

Fix: compute visibility once in `build_module_graph` as token to declaring
module per node (including global exports and re-export origins), copy it into
the registry, derive `available_providers` from it and validate exports
against the same mapping.

#### MG-04 Dependencies of non-singleton providers and controllers are never validated at bootstrap

Severity: medium. Category: design debt. Status: Confirmed (lead auditor, reproducer).

Where: `src/bustan/core/lifecycle/runner.py:81-87` (only singleton bindings are
pre-resolved), `src/bustan/platform/http/controller_factory.py:65-76` (singleton
controllers are built lazily), `src/bustan/app/bootstrap.py:57`,
`src/bustan/core/module/graph.py:196` (only exports and route metadata are
validated), `src/bustan/platform/http/execution.py:193` (the failure is logged
and becomes a generic 500).

Mechanism: `build_module_graph` never inspects constructor signatures. A
controller or a transient or request-scoped provider that depends on an
unregistered or invisible type passes `create_app` and the lifespan, then fails
on its first request. NestJS fails at compile time for all scopes.

Evidence: `repros/missing_dependency_only_fails_at_request_time.py`: `app
started; unresolvable controller dependency became HTTP 500`;
`repros/evidence/MG-04.py` shows `/ok/ -> 200` beside `/t/`, `/r/`, `/c/ -> 500`
and the singleton control failing at startup.

Impact: deployments pass health checks with broken routes; the eager singleton
check itself only runs when the lifespan or `init()` runs.

Fix: plan constructor parameters for every class binding and controller at
container build time without instantiating (the plan cache from CR-05) and
verify every non-special, non-optional token is visible from its module;
report all failures together from `create_app` and `create_app_context`.

#### MG-05 DynamicModule identity is id()-based

Severity: medium. Category: design debt. Status: Confirmed.

Where: `src/bustan/core/module/graph.py:106` (inputs keyed by `id()`),
`graph.py:113` and `:133-134` (`instance_id` from a pre-order counter),
`src/bustan/core/module/compiler.py:110` (`_validate_unique_entries` also uses
`id()`), `src/bustan/addons/module_ref.py:69`, `src/bustan/addons/discovery.py:82-89`
(first match by class).

Mechanism: `DynamicModule` is a frozen dataclass with value equality, but two
equal `for_root(opts)` calls produce two `ModuleInstanceKey`s with duplicated
bindings and singletons; `imports=[dm, dm_equal]` is accepted while
`[Mod, Mod]` raises; instance ids depend on discovery order, so unrelated
imports rename `ConfigModule[0]` to `[1]`; `ModuleRef.for_module` and
`DiscoveryService` silently return the first instance.

Evidence: `repros/evidence/MG-05.py`: `resolve(Counter, M1) is resolve(Counter,
M3): False`, `[dm, dm_equal] -> accepted`, `key of dmA when MA visited first:
instance_id=0` versus `1` when `MB` is visited first.

Fix: decide and document the identity rule: deduplicate by value (hashable
`DynamicModule` or a stable digest) so equal registrations share one instance,
or keep identity semantics and make `_validate_unique_entries` consistent and
instance ids stable; make `for_module` raise on ambiguity.

#### MG-06 Module classes are instantiated twice with no arguments

Severity: medium. Category: design debt. Status: Confirmed (two finders).

Where: `src/bustan/pipeline/middleware.py:158` (`node.module()` for every node,
unwrapped), `src/bustan/core/lifecycle/runner.py:63-71` (a second instantiation
for modules with hooks), `src/bustan/platform/http/scanner.py:120-131` (hook
methods on controllers rejected as non-route methods).

Mechanism: `compile_middleware_registry` instantiates every module to look for
`configure`, so a module `__init__` with parameters makes `create_app` fail
with a bare `TypeError` while `create_app_context` accepts the same module;
`configure` and `on_module_init` then run on different instances.

Evidence: `repros/evidence/MG-06.py`: `create_app_context(App1): OK` but
`create_app(App1) raised bare TypeError ... is BustanError: False`; `total
module instances created: 2`.

Fix: instantiate each module once into a shared map (through the container
so constructor injection works, or validated as no-arg), wrap failures in
`InvalidModuleError`, and pass the map to the middleware compiler; decide
whether controllers may declare hooks.

#### MG-07 Exporting a module class fails with a provider error and wrong advice

Severity: low. Category: API ergonomics. Status: Confirmed (lead spot check).

Where: `src/bustan/core/module/graph.py:219-223`, `docs/TROUBLESHOOTING.md:11`.

Mechanism: `exports=[SharedModule]` raises `ExportViolationError` naming the
module as an unavailable provider; the troubleshooting doc then tells the user
to add it to `providers`, which registers the module class as a binding.

Evidence: lead spot check: `Core exports Shared, but that provider is not
available (neither provided nor imported)`.

Fix: detect module and `DynamicModule` export entries and either implement
module re-export (with MG-01's origin tracking) or raise a targeted
`InvalidModuleError`; update the troubleshooting entry.

#### MG-08 A DynamicModule cannot override a token its base module declares

Severity: low. Category: API ergonomics. Status: Confirmed (lead spot check).

Where: `src/bustan/core/module/compiler.py:39-42` (providers concatenated
without deduplication), `compiler.py:92` (duplicates rejected).

Mechanism: the NestJS pattern of base defaults overridden by `for_root`
options is unavailable; `ConfigurableModuleBuilder` works only because its
generated base module is empty.

Evidence: `Base53[0] declares duplicate entries in providers:
InjectionToken('OPTS')`.

Fix: let dynamic providers replace base providers with the same token and
deduplicate imports and controllers by identity; document the precedence.

#### MG-09 Cycle detection through a DynamicModule reports no path

Severity: low. Category: code smell. Status: Confirmed (workflow reproducer, second pass).

Where: `src/bustan/core/module/graph.py:117-126` and `:137`.

Mechanism: when a cycle re-enters the same `DynamicModule` object,
`expand_module_input` assigns a fresh instance id, so the key-based detector
misses it and only the identity check fires with the whole dataclass repr and
no path. The `key in compiled_by_key` guard cannot trigger, and if it did its
early return would skip import traversal.

Fix: keep one detector that maps visiting inputs to their assigned key so the
path renders as `Root -> X[0] -> Y -> X[0]`; delete the unreachable branch and
the narrative comments around it.

#### MG-10 @Module accepts sets and a bare dict; double decoration overwrites silently

Severity: low. Category: API ergonomics. Status: Confirmed (lead spot check).

Where: `src/bustan/core/module/decorators.py` (`_coerce_tuple`),
`src/bustan/core/module/metadata.py:27`.

Mechanism: a set of providers makes binding order, eager construction order
and hook order hash-dependent between processes; a single provider dict
iterates its keys and fails later with `Invalid provider definition: 'provide'`;
applying `@Module` twice replaces the metadata.

Evidence: lead spot check: `providers={S}` accepted as a tuple in hash order;
`providers={"provide": ...}` reported as `Invalid provider in M52b: Invalid
provider definition: 'provide'`.

Fix: reject unordered collections and `Mapping` instances in `_coerce_tuple`
with targeted errors; raise when `set_module_metadata` finds existing own
metadata.

### 4.4 Provider definitions, metadata and tokens

#### PN-01 @Injectable metadata is inherited, so an undecorated subclass binds its parent

Severity: high. Category: correctness. Status: Confirmed (two finders, lead auditor).

Where: `src/bustan/core/ioc/registry.py:29-34` (`getattr(defn,
BUSTAN_PROVIDER_ATTR, {})` walks the MRO, then `meta.get("token", defn)` and
`meta.get("use_class", defn)`), `src/bustan/common/decorators/injectable.py:45-53`
(the metadata dict is a class attribute), `src/bustan/core/utils.py:51`
(`_get_metadata(inherit=False)` exists and is used for module and controller
metadata), `src/bustan/platform/http/controller_factory.py:125` (the same
inherited `getattr` decides whether a pipeline class is container-managed).

Mechanism: `providers=[Child]` yields `Binding(token=Parent, target=Parent,
scope=Parent's)`. `Child` is never registered or constructed; `resolve(Child)`
fails with `not available`; `providers=[Parent, Child]` raises a duplicate
error naming `Parent`. In the pipeline, an undecorated subclass of an
`@Injectable` guard is container-resolved under the wrong identity and returns
500 on every request, while a subclass of a plain guard works.

Evidence: `repros/injectable_metadata_inherited_by_subclass.py`:
`providers=[EmailNotifier] bound token=BaseNotifier target=BaseNotifier;
resolve(EmailNotifier): ... not available`; `repros/evidence/PN-01.py` adds
`@UseGuards(StrictGuard) with providers=[]: /x/strict -> 500`.

Fix: read provider metadata from `defn.__dict__` (or `_get_metadata(inherit=False)`)
in `normalize_provider` and `resolve_components`; when the metadata's token is
not the class itself, bind under the class's own identity or raise
`InvalidProviderError` asking for the decorator.

#### PN-02 A singleton whose value is None is never cached

Severity: high. Category: correctness. Status: Confirmed (lead auditor, reproducer).

Where: `src/bustan/core/ioc/scopes.py:51-52` (`dict.get`),
`src/bustan/core/ioc/resolver.py:128`, `:145`, `:250`, `:263` (`if cached is not
None`), `resolver.py:906-908`, `src/bustan/core/lifecycle/manager.py:112`,
`src/bustan/core/lifecycle/runner.py:87`.

Mechanism: every cache probe treats `None` as "not cached" while
`_cache_instance` stores `None`. A sync singleton factory returning `None`
re-executes on every resolution; an async factory returning `None` is warmed
once, does not satisfy the cache, and the following sync eager pass raises
`Initialize the application before resolving it synchronously` from inside
`init()`. Falsy non-`None` values are cached correctly.

Evidence: `repros/none_valued_singleton_rebuilt_every_resolve.py`:
`singleton factory ran 5 times for 5 resolves`; `repros/evidence/PN-02.py`:
`async None factory: init() -> ... uses an async factory. Initialize the
application before resolving it synchronously.`

Fix: use a private sentinel (`_MISSING` already exists at `resolver.py:931`)
for cache misses in `ScopeManager` and compare against it in the resolver.

#### PN-03 Overrides match tokens by identity while the registry matches by equality

Severity: medium. Category: correctness. Status: Confirmed (two finders).

Where: `src/bustan/core/ioc/overrides.py:55-59` (`registered_token is token`),
`overrides.py:47-49` (the `module=` path uses equality),
`src/bustan/testing/overrides.py:26`.

Mechanism: a runtime-built string or int token (`"".join(...)`, an f-string,
a config value, an int above 256) resolves fine through the dict-based
registry but the override scan says `is not registered in the container`;
`has_override` swallows the error and reports `False`, so `override_provider`
installs nothing.

Evidence: `repros/evidence/PN-03.py`: `ctx.get(runtime_token) -> 'real'` but
`override(runtime_token) raised ... 'client' is not registered in the
container`; passing `module=` makes it work.

Fix: use an equality-consistent lookup (a token to modules index maintained
by `Registry.register_binding`); `InjectionToken` keeps identity semantics
implicitly.

#### PN-04 Dict normalization ignores inject on use_class and validates nothing

Severity: medium. Category: API ergonomics. Status: Confirmed.

Where: `src/bustan/core/ioc/registry.py:46-82`, `src/bustan/core/ioc/resolver.py:387`
and `:528-545`.

Mechanism: `normalize_provider` tests `use_class`, `use_factory`, `use_value`,
`use_existing` in a fixed order and returns on the first hit, dropping the
other keys, unknown keys and `inject` on `use_class` silently; `inject` is
coerced with `tuple(...)`, so `inject="dep"` becomes `("d", "e", "p")`;
`use_class` and `use_factory` targets are not validated, so an instance or an
int is stored and fails at first resolution with an `AttributeError` or
`TypeError` that names neither the module nor the provider.

Evidence: `repros/evidence/PN-04.py`: `use_class+inject -> inject dropped`,
`inject='dep' -> inject tuple = ('d', 'e', 'p')`, `use_factory=42: resolve
raised builtins.TypeError: 'int' object is not callable (BustanError=False)`.

Fix: validate the dict shape: exactly one `use_*` key, no unknown keys, no
`inject` without `use_factory`, `inspect.isclass(use_class)`,
`callable(use_factory)`, no `str` or `bytes` for `inject`; raise with the key
names so the module compiler can add context.

#### PN-05 A registered but undecorated pipeline class is built with no arguments

Severity: medium. Category: parity gap. Status: Confirmed.

Where: `src/bustan/core/ioc/registry.py:55-56` (any class is a valid provider),
`src/bustan/platform/http/controller_factory.py:125-131` (the decorator attribute
alone decides whether to container-resolve), `src/bustan/platform/http/execution.py:140`.

Mechanism: `providers=[PlainGuard]` without `@Injectable` is a valid binding
with constructor injection and `ctx.get(PlainGuard)` works, but
`resolve_components` calls `PlainGuard()` and converts the `TypeError` into
`InvalidPipelineError` on every request.

Evidence: `repros/evidence/PN-05.py`: `container.get(PlainGuard) -> PlainGuard
policy injected: True`; `GET /x/ -> 500` twice; `InvalidPipelineError: Guard
PlainGuard must be an instance, a no-argument class, or an @Injectable
provider`.

Fix: check registry visibility first in `resolve_components` and
container-resolve registered classes regardless of decorator; validate
pipeline component classes at compile time.

#### PN-06 Invalid dict input escapes as raw TypeError or ValueError

Severity: low. Category: API ergonomics. Status: Confirmed (lead auditor, reproducer).

Where: `src/bustan/core/ioc/registry.py:44` (`ProviderScope(...)` raises
`ValueError`), `src/bustan/core/module/compiler.py:85-96` (only `TypeError`
from `normalize_provider` is translated; the hashability failure happens
outside the `try`), `src/bustan/common/decorators/injectable.py:35` (the
decorator does translate the same mistake).

Evidence: `repros/unhashable_token_raises_raw_typeerror.py`: `raw TypeError
escaped: unhashable type: 'dict'`; `repros/evidence/PN-06.py`: `scope='Request':
builtins.ValueError ... (BustanError=False)` while `@Injectable(scope='Request')`
raises `InvalidProviderError`.

Fix: wrap scope coercion, validate token hashability naming the module, and
extend the compiler's except clause to `(TypeError, ValueError)`.

#### PN-07 Provider metadata is a mutable dict trusted verbatim

Severity: low. Category: design debt. Status: Verified by reading.

Where: `src/bustan/common/decorators/injectable.py:45-53`,
`src/bustan/core/ioc/registry.py:29-35`.

Mechanism: `@Injectable` stores `{"scope", "token", "use_class"}` in a plain
dict and `normalize_provider` reads all three back without validation, so any
code can make the bare-class form bind a different token or target, or set an
invalid scope that surfaces as a raw `ValueError`. Controller metadata, by
contrast, is a frozen dataclass.

Fix: store a frozen `ProviderMetadata` holding only the scope, derive token
and target from the class itself, and read it without inheritance (PN-01).

#### PN-08 InjectionToken equality is identity-based and undocumented

Severity: info. Category: API ergonomics. Status: Verified by reading.

Where: `src/bustan/core/ioc/tokens.py:10-16`, `src/bustan/core/utils.py:21`.

Mechanism: two tokens with the same name are distinct (defensible) but error
messages render both as `InjectionToken('CONFIG')`, so providing one and
resolving the other gives no hint.

Fix: document identity semantics; include the defining module or `id()` in
the repr, or mention same-named registered tokens in the error.

#### PN-09 Factory inject lists cannot name REQUEST, RESPONSE, APPLICATION or INQUIRER

Severity: medium. Category: parity gap. Status: Confirmed (critic round).

Where: `src/bustan/core/ioc/resolver.py:383-386` and `:409-416` (every inject
entry goes through `resolve`, which starts with a visibility lookup),
`resolver.py:579` and `:719` (special tokens are recognized only by the
constructor planner), `src/bustan/core/ioc/registry.py:55` (the inject tuple is
accepted without validation).

Evidence: `repros/evidence/PN-09.py`: `inject=(REQUEST,) scope=request -> HTTP
500 ... InjectionToken('REQUEST') is not available to AppModule`; the same for
`RESPONSE`, `APPLICATION`, `INQUIRER` and for an async factory; the
constructor-injection control returns 200.

Impact: a request-aware factory provider cannot be written at all; the only
route to the request is a class provider with an annotated constructor. NestJS
supports `inject: [REQUEST]`.

Fix: route inject tokens through the same special-token resolution as the
constructor planner with the owner-scope rules of roadmap item 0.2; reject
special tokens in singleton factory inject lists at build time.

#### PN-10 Durable scope accepts targets that can never supply a key

Severity: low. Category: API ergonomics. Status: Confirmed (critic round).

Where: `src/bustan/core/ioc/resolver.py:833-846` (the key hook is read from
`binding.target`, which is a tuple for factories), `src/bustan/core/ioc/registry.py:44-62`
(no check at registration), `src/bustan/core/ioc/scopes.py:19-24` (the
`runtime_checkable` protocol is never used for validation).

Evidence: `repros/evidence/PN-10.py`: `{'use_factory': ..., 'scope': 'durable'}`
is accepted and fails on every resolve; a `get_durable_context_key` written as
an instance method is called unbound and raises a raw `TypeError`, an HTTP 500.

Fix: at normalization require durable bindings to be class bindings whose
target has a classmethod or staticmethod key hook (or accept a `durable_key`
callable for factories); wrap hook exceptions in `ProviderResolutionError`.

#### PN-11 StrEnum tokens silently alias bare strings

Severity: low. Category: correctness. Status: Confirmed (critic round).

Where: `src/bustan/core/ioc/registry.py:91-92` (dicts keyed on the raw token),
`src/bustan/core/ioc/container.py:58`, `src/bustan/core/module/compiler.py:91-96`,
`src/bustan/core/ioc/overrides.py:55-59`.

Evidence: `repros/evidence/PN-11.py`: a local `{"provide": "db"}` shadows an
imported `Tokens.DB` export (`get(Tokens.DB) -> 'string-db'`); the pair in one
module is rejected as a duplicate; `override(Tokens.DB, 'fake')` is accepted
and has no effect on the importing module; `True` and `1` alias the same way.

Fix: normalize tokens to a type-aware canonical key at registration and use
it in visibility, duplicate detection and overrides; emit a diagnostic when a
local binding shadows an imported export.

### 4.5 Constructor reflection and annotation resolution

#### RF-01 A visible provider with the same bare name hijacks a string annotation

Severity: high. Category: correctness. Status: Confirmed (lead auditor, reproducer).

Where: `src/bustan/core/ioc/resolver.py:803-825` (`_build_type_hint_namespace`
maps every visible token class by bare `__name__` with `setdefault`, local
bindings first, then imports in order), `resolver.py:540-547` (that namespace
is passed as `localns`, which `get_type_hints` consults before `globalns`).

Mechanism: with `from __future__ import annotations` (used throughout the
project and its scaffold) every annotation is a string, and the synthesized
namespace overrides lexical scoping. A constructor in `feature.py` that
annotates `cfg: Config` meaning `feature.Config` receives `shared.Config` if
a provider of that name is visible; import order flips the outcome; nothing is
logged.

Evidence: `repros/same_name_class_hijacks_annotation.py`: `feature.Config
annotation received collide_pkg.shared.Config`; `repros/evidence/RF-01.py`:
`imports=[AModule, BModule]: Consumer.repo is dup_a.Repo (lexical meaning:
dup_b.Repo)` while the reversed order is correct.

Impact: silent wrong-class injection with common names (`Config`, `Settings`,
`Logger`, `Repo`, `Client`).

Fix: evaluate hints with the constructor's own `__globals__` first and use
the synthesized namespace only for names lexical scope cannot resolve; when
two visible tokens share a `__name__`, omit both or raise naming the ambiguity.

#### RF-02 Optional[X] and X | None are opaque tokens; OptionalDep injects None although X is registered

Severity: high. Category: correctness. Status: Confirmed (lead auditor, reproducer).

Where: `src/bustan/core/ioc/resolver.py:783-801` (`_parse_dependency` unwraps
`Annotated` only), `resolver.py:592-596` (an unavailable `OptionalDep` token is
planned as `None`), `resolver.py:915-917` (membership test that a union object
never passes).

Mechanism: a union annotation becomes the token itself, which is never
visible. Without `OptionalDep` the failure is loud (`typing.Optional[Dep] is not
available`); with `OptionalDep` the planner substitutes `None` even though
`Dep` is provided in the same module.

Evidence: `repros/defaults_and_optional_unions_not_honored.py`: `UsesUnion:
... not available`; `repros/evidence/RF-02.py`: `UsesPipeNoneWithOptionalDep:
constructed, dep = None` while the `Annotated[Dep, OptionalDep()]` control
receives the `Dep`.

Fix: in `_parse_dependency` unwrap unions containing `NoneType` to the
non-`None` member with `optional=True`, or reject unions with a clear error;
never substitute `None` when the unwrapped class is visible.

#### RF-03 An inherited __init__ has its string annotations evaluated in the subclass module

Severity: medium. Category: correctness. Status: Confirmed (lead auditor, reproducer).

Where: `src/bustan/core/ioc/resolver.py:540-550` (`get_type_hints(constructor,
globalns=sys.modules[class_cls.__module__].__dict__)`; the function's own
`__globals__` is only the fallback when the module is missing).

Mechanism: an `__init__` inherited from a base class in another module must
be evaluated in that function's globals. Names that happen to be visible
tokens are rescued by the synthesized namespace (which is why RF-01 exists),
but `Inject`, `OptionalDep`, `Annotated`, token constants and type aliases
imported only in the base module raise `NameError`.

Evidence: `repros/inherited_init_annotations_wrong_namespace.py`: `Could not
resolve type hints for inherit_pkg.child.UserRepository.__init__: name 'Inject'
is not defined`; `repros/evidence/RF-03.py` adds a PEP 695 alias failing the
same way and the control that `get_type_hints` with the function's globals
succeeds.

Fix: use `constructor.__globals__` as `globalns` (falling back to the module
of the class that defines `__init__`), keeping the synthesized namespace as
`localns` only.

#### RF-04 Constructor defaults are ignored; OptionalDep substitutes None for the declared default

Severity: medium. Category: API ergonomics. Status: Confirmed (three finders, lead auditor).

Where: `src/bustan/core/ioc/resolver.py:568-570` (missing annotation raises
before the default is looked at), `resolver.py:578`, `resolver.py:592-596`.

Mechanism: `inspect.Parameter.default` is never read. `def __init__(self,
retries: int = 3)` fails with `builtins.int is not available`; `retries=3`
without an annotation fails with `missing a type annotation`;
`dep: Annotated[X, OptionalDep()] = SENTINEL` receives `None`, bypassing the
author's fallback.

Evidence: `repros/defaults_and_optional_unions_not_honored.py`: `UsesDefault:
... builtins.int is not available`; `repros/evidence/RF-04.py`:
`OptionalDepWithDefault -> dep = None | limit = None (declared default 10)`.

Fix: when a parameter has a default and its token is not visible, or is
unannotated, or is `OptionalDep`-marked and unavailable, omit the argument so
the default applies; fall back to `None` only when no default exists; document
the rule.

#### RF-05 APPLICATION resolves to three different types

Severity: medium. Category: API ergonomics. Status: Confirmed (lead auditor, reproducer).

Where: `src/bustan/core/ioc/resolver.py:754-759` (one branch serves both
`Inject(APPLICATION)` and a `Starlette` annotation and returns whatever was
pushed, else `request.app`), `src/bustan/app/application.py:60` (pushes the
`ApplicationContext`), `src/bustan/platform/http/adapters/starlette.py:38-54`
(pushes the `Application`), `src/bustan/addons/module_ref.py` and
`src/bustan/addons/discovery.py` (both special-case two of the shapes).

Evidence: `repros/application_token_resolves_to_three_types.py`:
`{'create_app_context': 'ApplicationContext', 'create_app': 'Application',
'http': 'Application', 'container.resolve(request=...)': 'Starlette'}`; a
parameter annotated `app: Starlette` receives an object for which
`isinstance(app, Starlette)` is `False` on the context path.

Fix: define `APPLICATION` as the Bustan `Application` or `ApplicationContext`
everywhere (normalize `request.app` through `state.bustan_application`) and
make a `Starlette` annotation return the underlying Starlette instance or
raise when there is none.

#### RF-06 APPLICATION is unavailable during lifespan startup

Severity: medium. Category: correctness. Status: Confirmed (two finders).

Where: `src/bustan/core/lifecycle/manager.py:45-59` (`startup` pushes nothing
while warming factories and instantiating every singleton),
`src/bustan/core/lifecycle/runner.py:87`, `src/bustan/app/application.py:60`
and `src/bustan/platform/http/execution.py:112` (the only two places that push
the application), `src/bustan/core/ioc/resolver.py:754`.

Mechanism: a singleton that injects `APPLICATION` works before `init()` and
in lazy resolution but fails eager instantiation with `requested APPLICATION,
which is not available`, as a raw `ProviderResolutionError` rather than the
`LifecycleError` the troubleshooting guide describes. The framework's own
`ModuleRef` and `DiscoveryService` avoid this only by being transient.

Evidence: `repros/evidence/RF-06.py`: `ctx.get(NeedsApp) before init -> OK`;
`ctx.init() raised RAW ProviderResolutionError`; `TestClient with lifespan ->
startup FAILED`; without lifespan `-> (200, {'app_type': 'Application'})`.

Fix: give `LifecycleManager` its owning context and push it around warm-up,
eager instantiation and hook stages; wrap eager-instantiation failures in
`LifecycleError`.

#### RF-07 The APPLICATION fallback leaks Starlette's KeyError

Severity: low. Category: correctness. Status: Confirmed.

Where: `src/bustan/core/ioc/resolver.py:758-759`.

Mechanism: `hasattr(request, "app")` swallows `AttributeError` only;
`HTTPConnection.app` is `self.scope["app"]`, so a request whose scope lacks
`app` raises `KeyError('app')` instead of reaching the `ProviderResolutionError`
branch. Only reachable when driving the container directly (unit tests, custom
adapters, middleware-built requests).

Evidence: `repros/evidence/RF-07.py`: `no-app request -> KeyError leaked`.

Fix: `active_request.scope.get("app")`.

#### RF-08 Classes that customize __new__ bypass injection with a raw TypeError

Severity: low. Category: correctness. Status: Confirmed.

Where: `src/bustan/core/ioc/resolver.py:528-530` (`object.__init__` short
circuit), `resolver.py:344`.

Evidence: `repros/evidence/RF-08.py`: `NewOnly: RAW TypeError: NewOnly.__new__()
missing 1 required positional argument: 'dep'`; dataclasses, `slots=True`
dataclasses and `__slots__` classes resolve correctly.

Fix: plan parameters from `__new__` when `__init__` is `object.__init__` and
`__new__` is overridden, or raise a `ProviderResolutionError` naming the
limitation.

#### RF-09 Multiple Inject markers on one parameter are accepted; the last wins

Severity: low. Category: code smell. Status: Confirmed (lead spot check).

Where: `src/bustan/core/ioc/resolver.py:791-793`.

Evidence: `Annotated[str, Inject("A"), Inject("B")]` resolved `from-B` with
no warning.

Fix: raise `ProviderResolutionError` on a second `InjectMarker`.

#### RF-10 ModuleRef and DiscoveryService cannot be resolved from ApplicationContext

Severity: medium. Category: API ergonomics. Status: Confirmed (critic round; the concrete consequence of RF-05).

Where: `src/bustan/app/application.py:60` (pushes the context itself as
`APPLICATION`), `src/bustan/addons/module_ref.py:20-22` and `:57-64`,
`src/bustan/addons/discovery.py:23-24` and `:72-79` (both accept only
`Application` or a Starlette app and raise `TypeError` otherwise),
`docs/LIFECYCLE.md:65-68` (presents `create_app_context` as the supported
non-HTTP entry point).

Evidence: `repros/evidence/RF-10.py`: `ctx.get(ModuleRef) -> RAW TypeError:
ModuleRef requires an Application runtime`; the same for `DiscoveryService`
and for any provider that injects `ModuleRef`; `create_app(...).get(ModuleRef)`
works.

Fix: accept `ApplicationContext` in both addons (they only need the
container, module graph and root key), or define `APPLICATION` as always
resolving to the context base type; wrap addon validation errors in
`ProviderResolutionError`.

#### RF-11 Constructor introspection edge cases

Severity: low. Category: correctness. Status: Confirmed (critic round).

Where: `src/bustan/core/ioc/resolver.py:542-545` (`constructor.__globals__` is
evaluated eagerly as a `getattr` default), `:550` (only `NameError` and
`TypeError` are caught), `:557` (the instance parameter is skipped by the
literal name `self`), `:579-592` (special tokens are resolved before the
`OptionalDep` branch).

Evidence: `repros/evidence/RF-11.py`: an `@Injectable` subclass of `dict` or
`Exception` raises a raw `AttributeError: 'wrapper_descriptor' object has no
attribute '__globals__'`; a malformed string annotation raises a raw
`SyntaxError`; `def __init__(this, dep: Dep)` fails on `this`;
`Annotated[object, Inject(REQUEST), OptionalDep()]` in a singleton raises
instead of yielding `None`.

Fix: compute `globalns` lazily, broaden the except clause and wrap, skip the
first parameter by position, and evaluate `OptionalDep` before raising for
unavailable special tokens.

### 4.6 Overrides, testing surface and lifecycle

#### OL-01 Overrides never reach already-built dependents

Severity: high. Category: correctness. Status: Confirmed (three finders, lead auditor).

Where: `src/bustan/core/ioc/container.py:117-125` (`override` and
`clear_override` clear controller singletons only), `src/bustan/core/ioc/scopes.py:158`,
`src/bustan/core/ioc/resolver.py:119-120` and `:127-129` (the override is
consulted only for the resolved token; a cached singleton is returned before
anything else), `src/bustan/core/lifecycle/runner.py:81` (startup builds every
singleton), `src/bustan/testing/overrides.py:31`, `README.md` (presents
`override_provider` as a scoped override restored automatically).

Mechanism: provider singletons, durable instances and request caches are
untouched by an override. Inside `with TestClient(app)` the lifespan has
already built every singleton, so `override_provider` affects only controllers
that inject the token directly; every singleton depending on it keeps the
production object. Conversely a singleton first built during the override
keeps the fake after the block exits.

Evidence: `repros/override_leaves_dependents_stale.py`: `ReportService still
used the real Clock during the override`; `repros/evidence/OL-01.py`: inside
the override `/hello/direct -> fake` but `/hello/transitive ->
welcome:production`; after the block `WelcomeService.welcome() -> welcome:fake`.

Impact: tests silently exercise real databases and HTTP clients while
believing they are faked.

Fix: either make overrides bootstrap-only (register before startup, raise
afterwards, as NestJS's testing module does) or record dependency edges during
construction and evict every cached instance that transitively depends on the
token on `override` and `clear_override`; document the rule in the README and
API reference either way.

#### OL-02 Global pipeline providers are baked at compile time

Severity: high. Category: correctness. Status: Confirmed (two finders, lead auditor).

Where: `src/bustan/platform/http/compiler.py:123-127` (`RouteCompiler` resolves
`APP_GUARD`, `APP_PIPE`, `APP_INTERCEPTOR`, `APP_FILTER` once inside
`_create_app`), `src/bustan/core/ioc/container.py:133-139`,
`src/bustan/core/module/compiler.py:92-96` (one binding per token per module),
`src/bustan/testing/builder.py:202` (`create_test_app` applies overrides after
compilation).

Mechanism: the instances are baked into every route contract before the
`Application` exists and before any lifespan. `create_test_app(provider_overrides=...)`
and `override_provider` mutate the override manager afterwards, so neither
affects the baked guards while `has_override` reports `True`. A second
`APP_GUARD` in one module is a duplicate-token error, a request-scoped
`APP_GUARD` fails with `requires an active request`, and a guard depending on
an async factory fails with `Initialize the application before resolving it
synchronously` with no earlier point to initialize.

Evidence: `repros/app_guard_cannot_be_request_scoped_one_per_module.py`
(`RESULT: OL-02a/b REPRODUCED`); `repros/evidence/OL-02.py`:
`has_override(APP_GUARD): True | GET /secure/ -> 403` for both override
mechanisms; the control that declares `AllowAll` in the module returns 200.

Impact: a test that believes it disabled a global guard is lying; global
pipeline components cannot be request-scoped or depend on async factories.

Fix: resolve `APP_*` providers lazily per request through
`ControllerFactory.resolve_components`, which already supports request-scoped
components, and collect a list per module for multiple bindings; or
re-resolve on override and make `Container.override` raise for `APP_*` tokens
after compilation.

#### OL-03 bustan.testing re-implements lifecycle orchestration and has drifted

Severity: high. Category: correctness. Status: Confirmed (four finders).

Where: `src/bustan/testing/builder.py:96-110` (`close` runs shutdown and
destroy only, raises `errors[0]`, has no closed flag), `builder.py:163-164`
(`compile` calls `run_init_hooks` and `run_bootstrap_hooks` directly),
`src/bustan/core/lifecycle/manager.py:46-51` (`startup` warms async factories
first).

Mechanism: `compile()` skips `_warm_async_factories`, so any graph with an
async singleton factory (and any `use_class` or `use_factory` replacement
resolved synchronously) raises `uses an async factory. Initialize the
application before resolving it synchronously`. `close()` never runs
`before_application_shutdown`, re-runs hooks on a second call, reports only the
first error, and leaves `LifecycleManager` unaware so `compiled.application.close()`
is a no-op while `application.init()` runs init hooks a second time.
`bustan.testing` is a documented stable surface.

Evidence: `repros/evidence/OL-03.py`: `create_app_context(AsyncApp).init() ok`
but `create_testing_module(AsyncApp).compile() ProviderResolutionError`; the
event trace after `compile()` and `close()` has no `before_shutdown`; a second
`close()` re-runs shutdown and destroy.

Fix: have `compile()` register value overrides and then call
`LifecycleManager.startup()`, construct replacements through the async paths,
and make `close()` delegate to `LifecycleManager.shutdown()`; delete the
hand-rolled sequencing.

#### OL-04 Lifecycle hooks are duck-typed onto every cached singleton

Severity: medium. Category: correctness. Status: Confirmed (lead auditor, reproducer).

Where: `src/bustan/core/lifecycle/runner.py:102-108` (`getattr(instance,
hook_name)` over `scope_manager.singletons.values()`), `src/bustan/core/ioc/registry.py:62-69`
(`use_value` is singleton and lands in the same table),
`src/bustan/core/lifecycle/hooks.py:9` (the `runtime_checkable` protocols are
never used).

Mechanism: no opt-in, no bound-method check, no identity dedup. A class object
handed over as a value whose instances define hooks is called unbound and
fails startup with `Provider lifecycle hook type.on_module_init failed`;
`MagicMock` and `AsyncMock` values receive all five hooks; one object bound
under two tokens gets each hook twice.

Evidence: `repros/lifecycle_hooks_duck_typed_on_value_providers.py`: all five
hooks invoked on a `use_value` `MagicMock`; `repros/evidence/OL-04.py`:
`use_value=class with instance hook: LifecycleError ... missing 1 required
positional argument: 'self'`; `events=['init', 'init', 'destroy', 'destroy']`.

Fix: run provider hooks only on instances the container constructed from
class or factory bindings, dedupe by `id()` per stage, skip `use_value` unless
opted in, and name the token in the error.

#### OL-05 A startup failure after on_module_init runs no teardown

Severity: medium. Category: correctness. Status: Confirmed.

Where: `src/bustan/core/lifecycle/manager.py:51-58` (state assigned only after
every stage succeeds), `manager.py:62-64` (`shutdown` returns when not
initialized), `src/bustan/app/lifespan.py:19-25` (the startup await is outside
the `try`), `docs/LIFECYCLE.md:88`.

Evidence: `repros/evidence/OL-05.py`: `events after failed init():
['poolmodule:init', 'pool:open']`, `events after close(): [same]`, `lifecycle
state: LifecycleState(initialized=False, closed=False, module_instances={})`,
identical over the HTTP lifespan.

Fix: record module instances and a stages-started marker as soon as
instantiation begins and run teardown for what has begun before re-raising;
move the startup await inside the lifespan's `try`.

#### OL-06 Overrides cannot target DynamicModule registrations through module_cls

Severity: medium. Category: API ergonomics. Status: Confirmed (two finders).

Where: `src/bustan/core/ioc/overrides.py:47-49` and `:70`,
`src/bustan/testing/overrides.py:21-31`, `src/bustan/testing/builder.py:123`.

Mechanism: dynamic registrations are keyed by `ModuleInstanceKey`; passing the
module class raises `not registered in ConfigModule`; the ambiguity error says
`specify module_key` but the real keywords are `module` and `module_cls`, and
`TestingModuleBuilder.override_provider` accepts no module at all.

Evidence: `repros/evidence/OL-06.py`: `(a) module_cls=ConfigModule ->
ProviderResolutionError: ... is not registered in ConfigModule`; `(c) override
with internal ModuleInstanceKey -> fake`.

Fix: accept a module class (matching every instance key for it, erroring only
on more than one match) and the `DynamicModule` object itself; add `module=`
to the builder chain; name the real parameter in the error.

#### OL-07 Overridden providers receive no lifecycle hooks

Severity: medium. Category: correctness. Status: Confirmed.

Where: `src/bustan/core/ioc/resolver.py:119-120` (the override is returned
before any cache write), `src/bustan/core/lifecycle/runner.py:102`.

Evidence: `repros/evidence/OL-07.py`: builder `use_class(FakeDb)` with hooks on
both classes: `hook events: []`, `singletons: []`; a late override leaves the
real instance receiving `on_module_destroy` while the fake gets nothing.

Fix: treat an override for a singleton binding as the singleton instance
(store it under the binding key, evicting the previous one) so hooks run; or
document overrides as opaque values excluded from lifecycle.

#### OL-08 TestingModuleBuilder builds replacements from the root module

Severity: medium. Category: correctness. Status: Confirmed.

Where: `src/bustan/testing/builder.py:145-161`.

Evidence: `repros/evidence/OL-08.py`: `FakeUserService.__init__ parameter 'db'
in AppModule failed to resolve Db ... not available to AppModule` although the
override manager knows the declaring module is `UsersModule`; the same
replacement constructs fine from `UsersModule`.

Fix: resolve replacements with the declaring module of the overridden token
and construct them lazily through a class or factory override kind so async
dependencies and hooks work.

#### OL-09 Async factories work for singleton scope only

Severity: medium. Category: design debt. Status: Confirmed (two finders).

Where: `src/bustan/core/ioc/container.py:96-115` (no `instantiate_class_async`
or `call_factory_async`), `src/bustan/platform/http/controller_factory.py:53-76`,
`src/bustan/platform/http/execution.py:122`, `src/bustan/core/ioc/resolver.py:131-135`,
`src/bustan/core/lifecycle/manager.py:102`.

Evidence: `repros/evidence/OL-09.py`: `scope=request status=500`,
`scope=transient status=500`, `scope=singleton status=200`; the underlying error
says `Initialize the application before resolving it synchronously` for an
application that is already initialized.

Fix: route request execution through the async resolver (`execute_http_route`
is already async) and expose `Container.instantiate_class_async`; or reject
async factories for non-singleton scopes at normalization time with a clear
message and document the limitation.

#### OL-10 Three inconsistent "is this factory async" predicates

Severity: medium. Category: correctness. Status: Confirmed.

Where: `src/bustan/core/ioc/resolver.py:919-923` and
`src/bustan/core/lifecycle/manager.py:106-110` (`inspect.iscoroutinefunction`),
`resolver.py:387-393` and `:417` (`isawaitable(result)` after calling).

Evidence: `repros/evidence/OL-10.py`: a callable object with `async __call__`
and a sync wrapper returning a coroutine both pass `init()` unwarmed, then
`ctx.get` raises `returned an awaitable during synchronous resolution` and
leaks `coroutine ... was never awaited`.

Fix: compute `Binding.is_async` once at normalization from the unwrapped
callable and `type(factory).__call__`, use it everywhere, and close the
coroutine before raising.

#### OL-11 No public way to resolve request-scoped providers from handler or guard code

Severity: medium. Category: API ergonomics. Status: Confirmed (two finders, lead auditor).

Where: `src/bustan/platform/http/execution.py:112-114` (application and
response are pushed for the request's lifetime; the request only inside
resolve calls), `execution.py:164`, `src/bustan/core/ioc/resolver.py:113`,
`src/bustan/addons/module_ref.py:46-48`, `src/bustan/app/application.py:53-58`
(the docstring points to `app.resolve()`, which is an alias of `get()`).

Evidence: `repros/module_ref_cannot_reach_request_scope_in_handler.py`:
`ProviderResolutionError: Request-scoped provider ... requires an active
request` from inside a handler; `repros/evidence/OL-11.py` shows
`active_request = NoneType` in sync and async handlers and in a guard while
`active_response` and `active_application` are populated; only the internal
`container.resolve(..., request=)` works.

Fix: push the native request for the whole `execute_http_route` body and add
a request-aware public entry point (`ModuleRef.get(token, request=...)` or
`ExecutionContext.resolve`); rewrite the `get()` docstring and regenerate the
API reference.

#### OL-12 Durable instances are excluded from warm-up and every lifecycle stage

Severity: low. Category: design debt. Status: Confirmed (lead spot check).

Where: `src/bustan/core/lifecycle/runner.py:85`, `:102`,
`src/bustan/core/lifecycle/manager.py:105`.

Evidence: a durable `TenantPool` with `on_module_destroy`: `destroy hooks run:
0 of 3` after a clean lifespan exit.

Fix: include `durable_instances.values()` in the three teardown stages
(reverse creation order) and call `on_module_destroy` on eviction (CR-01).

#### OL-13 Shutdown leaves caches populated and startup is one-shot

Severity: low. Category: design debt. Status: Confirmed (lead spot check).

Where: `src/bustan/core/lifecycle/manager.py:46-47` and `:92`,
`src/bustan/app/application.py:62`, `src/bustan/app/lifespan.py:19`.

Evidence: after `init()` and `close()`, `ctx.get(Pool)` returns the destroyed
pool and `ctx.init()` raises `Application lifecycle is already closed`; a
second `with TestClient(app)` over the same `Application` fails the same way.

Fix: either clear caches and reset state on shutdown so startup can run again,
or make `get()` raise after close; document the choice.

#### OL-14 The aggregated shutdown LifecycleError discards the individual exceptions

Severity: low. Category: API ergonomics. Status: Confirmed (lead spot check).

Where: `src/bustan/core/lifecycle/manager.py:94-98`,
`src/bustan/core/lifecycle/runner.py:50-52` and `:119` (`__cause__` set and
then `raise ... from`).

Evidence: two failing teardown hooks: `LifecycleError('2 lifecycle hooks
failed ...')` with `__cause__ None`, not an `ExceptionGroup`.

Fix: raise a `LifecycleError` that is also an `ExceptionGroup` (Python 3.13 is
the floor) or attach the errors and chain the first.

#### OL-15 Provider hook order mixes leaf-first async warm-up with root-first sync instantiation

Severity: info. Category: docs drift. Status: Confirmed (lead spot check).

Where: `src/bustan/core/lifecycle/manager.py:103` (`reversed(nodes)`),
`src/bustan/core/lifecycle/runner.py:85-102`, `docs/LIFECYCLE.md:17` and `:30`.

Evidence: for `Root -> Leaf` with async factories in both and a sync singleton
in root, the init order is `['LeafAsync', 'RootAsync', 'RootSvc']`.

Fix: warm async factories in graph order or use a single async eager pass in
node order; document that provider hooks run in construction order.

#### OL-16 The lifecycle signal argument is documented but never supplied

Severity: info. Category: docs drift. Status: Confirmed (critic round).

Where: `src/bustan/core/lifecycle/manager.py:61` (`shutdown(*, signal=None)`),
`src/bustan/app/lifespan.py:25` and `src/bustan/app/application.py:83` (the
only callers, both without a signal), `docs/LIFECYCLE.md:9-10`, `:43-44`, `:61-62`.

Evidence: `repros/evidence/OL-16.py`: both shutdown paths deliver
`signal=None` to every hook; no caller passes `signal=`.

Fix: wire a signal source (record the received signal in `Application.listen`
and pass it to `shutdown`) or remove the parameter from the documented hook
signatures until it exists.

### 4.7 Code quality, architecture and typing

#### QA-01 Layering violations: core imports the HTTP platform and Starlette

Severity: medium. Category: design debt. Status: Confirmed.

Where: `src/bustan/core/module/graph.py:17-20` (the module graph imports
`platform.http.metadata` to validate routes), `src/bustan/core/ioc/resolver.py:15-17`
and `:29-30` (Starlette `Request`, `Response`, `Starlette` imported; the
unused `FRAMEWORK_OWNED_TYPES` and `ResolvedT`), `resolver.py:732` and `:812`
(special-token resolution keyed on those exact classes and injected into the
type-hint namespace), `src/bustan/core/ioc/scopes.py:11`, `src/bustan/core/ioc/container.py:7`.

Mechanism: the module graph cannot exist without the HTTP platform, and the
IoC kernel is coupled to Starlette types although the project advertises an
adapter-neutral platform layer. The adapter-neutral `HttpRequest` documented
for handler parameters is not injectable into providers at all.

Evidence: `repros/evidence/QA-01.py`: `provider annotated with starlette
Request: 200` versus `provider annotated with HttpRequest: 500` with
`HttpRequest is not available to AppModule` in the log; both unused symbols
have zero references.

Fix: move route validation into the platform compiler; make `REQUEST`,
`RESPONSE` and `APPLICATION` opaque context slots with an adapter-populated
mapping of concrete classes (including `HttpRequest`); delete the dead symbols.

#### QA-02 The resolver is an 846-line class with eight drifting sync and async twins

Severity: medium. Category: design debt. Status: Measured.

Where: `src/bustan/core/ioc/resolver.py:83-928`.

Measurement (`repros/evidence/QA-02.py`, AST-based): 32 methods; eight twin
pairs (`resolve`, `_resolve_binding`, `instantiate_class`, `call_factory`,
`_resolve_constructor_dependencies`, `_resolve_declared_dependency`,
`_construct_binding`, `_shared_instance_slot` against
`_shared_async_construction_lock`) totalling 203 async-side lines with 0.55 to
1.00 similarity; six methods take six to eight parameters. Drift already
present: the sync `resolve` checks `_binding_requires_async` and stores
through a closure under a `threading.Lock`, while `resolve_async` has no such
guard and stores through `_cache_instance` (CR-02); coverage shows the async
durable lock branch, the async override hit and the async double-checked
cache are never executed by the suite.

Impact: every scope or guard change touches four to eight sites and a missed
replica ships silently through the untested twin.

Fix: one planning core with sync and async drivers that differ only in how a
leaf is awaited (or commit to async-first with a sync facade, see OL-09);
split special tokens, scope guard and caching into separate collaborators.

#### QA-03 Formatting and lint are not enforced

Severity: low. Category: code smell. Status: Measured.

Where: `src/bustan/core/ioc/resolver.py` (tab-indented; 801 `W191` hits),
`pyproject.toml:81-84` (`[tool.ruff]` selects no rules beyond the default),
`.github/workflows/ci.yml` and `lefthook.yml` (no `ruff format --check`),
`src/bustan/core/module/graph.py:90` (trailing whitespace lines).

Measurement: `ruff format --check src` would reformat 40 of 94 files;
selecting `I`, `UP`, `B`, `W` on the DI packages reports several hundred
findings (unsorted imports in nine files, deprecated typing imports,
`getattr` with constant attribute names).

Impact: every PR touching the resolver either preserves tabs by hand or
produces a 900-line whitespace diff that hides the semantic change.

Fix: run `ruff format` once in a dedicated commit listed in
`.git-blame-ignore-revs`; add `ruff format --check` to CI and lefthook; set
`[tool.ruff.lint] select = ["E", "F", "W", "I", "UP", "B", "SIM"]`.

#### QA-04 Stale comments, dead branches and misleading docstrings

Severity: low. Category: code smell. Status: Verified by reading.

Where: `src/bustan/core/module/graph.py:116` and `:159` (thinking-aloud
comments that reference tests), `src/bustan/common/decorators/injectable.py:38`
(a stale migration comment), `src/bustan/core/lifecycle/runner.py:50` and
`:119` (`__cause__` assigned and then `raise ... from`),
`src/bustan/core/ioc/resolver.py:681-682` (the `isinstance(annotation, str)`
early return is unreachable because `get_type_hints` evaluates or raises; the
suite never executes it), `resolver.py:809` (the constructed class's own name
is seeded first, so a class sharing a name with a token it depends on fails
with a message naming the wrong class), `src/bustan/core/lifecycle/hooks.py`
(a tuple named `LifecycleHookName`), unused `ResolvedT` and
`FRAMEWORK_OWNED_TYPES`, notes in `core/module/compiler.py` referencing
functions that do not exist.

Fix: replace narrative comments with one sentence per invariant (pre-order
node sequence is relied on by `container.py` and `runner.py`); delete the dead
branch, unused names and phantom notes; drop the manual `__cause__`
assignments; rename the tuple; fix the docstrings.

#### QA-05 Typing debt at the DI boundary

Severity: low. Category: typing debt. Status: Confirmed (workflow reproducer, second pass, using `reveal_type`).

Where: `src/bustan/app/application.py:44-58` (`root_module`, `root_key` and
`get` return `Any`), `src/bustan/core/ioc/container.py:71` (`resolve` returns
`object`), `src/bustan/core/ioc/tokens.py:10` (`InjectionToken[T]` is generic
but no signature is overloaded on it), `src/bustan/core/ioc/registry.py:18-20`
(`resolver_kind` is a free `str`, `target` is `object`, `scope` is not coerced;
`Binding` and `ModuleNode` are `frozen=True` with `eq=True`, so an unhashable
`use_value` makes a node unhashable).

Impact: no static typing from the DI API despite the `Typing :: Typed`
classifier; `Binding("tok", M, "vlaue", 1, SINGLETON)` type-checks and fails
only at resolve time in a branch no test executes.

Fix: make `Binding` a tagged union (or `Literal` kinds with typed targets) and
coerce scope in `__post_init__`; add `@overload`s so `get(InjectionToken[T])`
returns `T` and `get(type[T])` returns `T`; type `root_key` as `ModuleKey`;
declare `eq=False` on the frozen dataclasses.

#### QA-06 Container internals are public mutable dicts

Severity: low. Category: API ergonomics. Status: Confirmed (workflow reproducer, second pass).

Where: `src/bustan/core/ioc/registry.py:91-93`, `src/bustan/core/ioc/scopes.py:31-39`,
`src/bustan/app/application.py:33` (`app.container` is a documented accessor),
`docs/PLATFORM_INTEGRATION.md:13`.

Mechanism: `Registry.bindings`, `module_visibility`, `controller_modules` and
every `ScopeManager` cache are plain attributes; mutating `module_visibility`
grants access to non-exported providers, bypassing graph validation; the
framework's own consumers already reach in directly.

Fix: expose read-only views (`MappingProxyType`) and explicit methods for the
operations consumers need.

#### QA-07 ModuleKey is a raw union duck-typed through hasattr probes

Severity: low. Category: code smell. Status: Verified by reading.

Where: `src/bustan/core/module/dynamic.py:13-17`, `src/bustan/core/utils.py:8-29`
(`hasattr(target, "module") and hasattr(target, "instance_id")` to avoid a
circular import), `src/bustan/addons/discovery.py:82` (duck-typed node
lookup with no return annotation although `ModuleGraph.get_node` exists).

Fix: move `ModuleInstanceKey` (or a `Protocol`) so `isinstance` can be used;
validate `module` in `__post_init__`; type `_resolve_module_node` with
`ModuleNode`.

#### QA-08 Tooling drift

Severity: low. Category: docs drift. Status: Measured (one sub-claim did not hold).

Where: `pyproject.toml:95-97` (`[tool.uv.workspace] members = ["mini"]` with no
such directory), `pyproject.toml:76` (`fail_under = 95` applies to every
`--cov` invocation), `.github/workflows/ci.yml:33` and `lefthook.yml:7` (`ty`
runs on `examples` locally but not in CI).

Measurement: `uv run pytest tests/unit/core/ioc --cov=bustan.core.ioc`
exits red with `Required test coverage of 95.0% not reached. Total coverage:
87.75%` while all 38 tests pass; a plain `uv run` rewrites one metadata line of
`uv.lock` on every invocation (dirtying the tree), although `uv lock --check`
passes, so the original "lock out of sync" claim is only partly true.

Fix: remove the workspace table; commit the one-line lock refresh and add
`uv lock --check` to CI; move `fail_under` to the CI command line; align the
`ty` path lists.

#### QA-09 Test gaps around the kernel

Severity: low. Category: testing gap. Status: Measured and confirmed (workflow reproducer, second pass).

Where: whole-suite branch coverage misses `resolver.py` lines 125, 222-224,
242, 247, 264, 298, 302, 304, 325, 420, 427, 492-493, 534-535, 610-614,
666-667, 682 and `scopes.py` 112, 121, 148, 152; `lifecycle/hooks.py` is at
79 percent.

Mechanism: the suite never executes the sync `Binding not found` branch,
durable async locks, override hits in `resolve_async`, the async
double-checked cache, `Unknown resolver kind`, value and existing bindings on
the async path, `_detect_owner_scope`, an uninspectable `__init__`, or
`clear_request_state`; no test references `get_global_pipeline_providers`,
controller singleton locking or `instantiate_class_async`. What is enforced
today (singleton class depending on a request-scoped class, singleton provider
taking `Request`, request-scoped resolution outside a request, per-request
cache clearing) is tested; the documented rule for singleton controllers,
factory `inject` lists, aliases, durable dependencies, `RESPONSE`, `INQUIRER`
and lazy construction without a lifespan are not, which is why RI-01 through
RI-09 stayed latent. The 95 percent global gate is met by other packages.

Fix: see section 7.

#### QA-10 ContextVars are created per container instance

Severity: info. Category: code smell. Status: Confirmed (lead spot check).

Where: `src/bustan/core/ioc/scopes.py:41-49`, `src/bustan/core/ioc/resolver.py:95-102`.

Evidence: with a request pushed through one container's `ScopeManager`, a
second container's `active_request.get()` returns `None`.

Fix: declare the `ContextVar`s once at module scope, or document per-container
isolation as intended.

#### QA-11 The coverage gate is nominal

Severity: medium. Category: testing gap. Status: Confirmed (round two).

Where: `pyproject.toml:76-77` (`fail_under = 95`, default precision 0),
`.github/workflows/ci.yml:43`, `lefthook.yml:12`.

Evidence: `repros/evidence/QA-11.py` runs the exact CI command: `TOTAL ... 95%`
alongside `FAIL Required test coverage of 95.0% not reached. Total coverage:
94.53%`, exit code 0. pytest-cov decides pass or fail with
`should_fail_under(total, 95, precision=0)`, which rounds 94.53 to 95, while
the summary line compares the unrounded value; the effective threshold is 94.5
and the kernel files sit well below it (resolver 92, scopes 92, lifecycle
runner and manager 90, hooks 79 percent).

Fix: set `precision = 2` so the comparison is honest, raise coverage or lower
the number, add a stricter separate gate for `bustan.core.ioc` and
`bustan.core.lifecycle`, and stop counting protocol bodies as missed
statements.

#### QA-12 The suite pins known-defective behaviors as contracts

Severity: medium. Category: testing gap. Status: Confirmed (round two).

Where: `tests/unit/core/ioc/test_registry.py:53-60` and `:73-79` (asserts the
silent scope drop of RI-02 and the raw `TypeError` of PN-06),
`tests/unit/core/ioc/test_resolver.py:53-71` (asserts that a non-controller,
non-request owner receives `RESPONSE` and `APPLICATION`, the mechanism of
RI-05), `tests/integration/platform/test_exception_filters.py:81-107` (composes
a request-scoped provider into a default controller and asserts a 500, the
shape of RI-01 and EX-01), `tests/unit/core/module/test_dynamic_modules.py:34-49`
and `:114-136` (accepts the re-export of MG-01 and the collision of MG-02
without resolving), `tests/unit/testing/test_testing_builder.py:101-115`
(locks in `close()` skipping `before_application_shutdown`, OL-03),
`tests/unit/core/module/test_metadata.py:13-26` (pins non-inheritance for
module and controller metadata while `@Injectable` inherits, PN-01).

Evidence: `repros/evidence/QA-12.py` checks each assertion text and executes
the runtime; all 14 checks hold.

Impact: fixing the corresponding defects turns green tests red, and the
natural reaction is to revert the fix.

Fix: convert each into an `xfail(strict=True)` test that states the intended
behavior, so the suite documents the target contract instead of the defect.

#### QA-13 Provider hook failure paths and lifecycle re-entrancy are untested

Severity: medium. Category: testing gap. Status: Confirmed (round two).

Where: `src/bustan/core/lifecycle/runner.py:114-122` (the whole except block of
`run_provider_lifecycle_stage`), `runner.py:68-69`, `src/bustan/core/lifecycle/manager.py:46-49`
and `:95-98`, all reported as never executed by the suite.

Fix: tests for a provider hook that raises at startup and at teardown, two
failing teardown hooks aggregated, startup twice, shutdown twice, startup
after shutdown, and a module class whose `__init__` needs arguments.

#### QA-14 The resolver is tested through private seams on hand-built registries

Severity: medium. Category: testing gap. Status: Confirmed (round two).

Where: `tests/unit/core/ioc/test_resolver.py` (three tests, 29 direct calls to
underscore methods, zero calls to `container.resolve` or `instantiate_class`),
`tests/unit/app/test_application_internals.py:44-50`.

Mechanism: the tests pass `owner_is_controller` and `is_request_scoped` by
hand, so they never exercise how those flags are derived
(`_detect_owner_scope`, lines 607-615, uncovered), how the construction stack
is populated, or how visibility is computed; refactoring the resolver breaks
them without saying whether observable behavior changed.

Fix: re-express them as black-box tests over a real module graph with real
`Request` objects, keeping at most a thin seam test for `_parse_dependency`.

#### QA-15 Override-by-scope, durable-over-HTTP and dynamic-module override categories are untested

Severity: medium. Category: testing gap. Status: Confirmed (round two).

Where: `tests/integration/testing/test_testing_utilities.py:10` and `:47`,
`tests/unit/core/ioc/test_durable_scope.py:16-85`, `tests/unit/core/module/test_dynamic_modules.py:34`.

Evidence: `repros/evidence/QA-15.py`: overriding a request-scoped, durable or
transient provider serves one shared fake to every request and tenant and the
`use_existing` alias silently follows; a request-scoped override resolves
with no active request; none of this is pinned by a test, and no test touches
durable scope over HTTP, a `None` durable key, durable lifecycle hooks or
eviction, or overrides of `DynamicModule` providers.

Fix: the test modules named in section 7 (override scopes, durable over HTTP,
dynamic-module overrides).

#### QA-16 Tautological tests and duplicated fixtures inflate the count

Severity: low. Category: testing gap. Status: Verified by reading and measurement.

Where: `tests/unit/core/ioc/test_registry.py:83`, `tests/unit/core/ioc/test_tokens.py:7`,
`tests/unit/core/lifecycle/test_hooks.py:26` and `:116`,
`tests/unit/testing/test_testing_builder.py:90` and `:237-277`,
`tests/unit/core/module/test_dynamic_modules.py:108`.

Measurement: `_build_request` is defined 13 times across the tests with six
distinct signatures; the `isinstance` checks against the lifecycle protocols
exercise a path the framework never uses (the runner duck-types through
`getattr`); the builder's pipe, interceptor and filter overrides are asserted
through the private `_pipeline_overrides` dicts and never through a request,
although an end-to-end test works; the dynamic-module cycle test fabricates a
state no public API can produce.

Fix: a shared request factory in `conftest.py`, end-to-end tests for the
pipeline overrides, exact event ordering in the hooks test, and cycles built
through public constructors.

### 4.8 Documentation drift and NestJS parity

#### DP-01 ModuleRef injected through DI is always root-scoped

Severity: medium. Category: parity gap. Status: Confirmed.

Where: `src/bustan/addons/module_ref.py:20-22` (`_module_key = application.root_key`
regardless of the receiving module), `module_ref.py:46-48` (`strict=False`
also resolves against the root), `docs/API_REFERENCE.md:849-866` (signature
only, no semantics).

Evidence: `repros/evidence/DP-01.py`: `ModuleRef` injected into a
`ChildModule` service reports `module_key = AppModule`; `get(PrivateInChild)`
fails for both `strict` values; `for_module(ChildModule).get(...)` works.

Fix: resolve `ModuleRef` as a special token using the module key of the class
being constructed; implement `strict=False` as a search over all bindings
with an ambiguity error; document the semantics.

#### DP-02 for_root_async and register_async cannot see the importing module's providers

Severity: low. Category: parity gap. Status: Confirmed (lead spot check).

Where: `src/bustan/core/module/builder.py:102-131` (the generated
`DynamicModule` carries providers and exports only), `docs/API_REFERENCE.md:1342`.

Evidence: `for_root_async(use_factory=make, inject=(HostConfig,))` imported by
a module that provides `HostConfig`: `HostConfig is not available to
CacheModule[0]`.

Fix: add an `imports=(...)` keyword forwarded to `DynamicModule.imports`;
document the `@Global` workaround until then.

#### DP-03 Smaller NestJS parity gaps

Severity: low. Category: parity gap. Status: Confirmed (workflow reproducer, second pass, for the executable parts).

- `INQUIRER` yields the requesting class, not the instance
  (`resolver.py:770-779`); the API reference calls it only "a typed token".
- A NestJS-style `{"token": X, "optional": True}` entry in a factory `inject`
  list raises `TypeError: unhashable type: 'dict'` from the visibility lookup
  (`registry.py:55`, `resolver.py:431`).
- Circular provider and module dependencies always raise; there is no
  `forwardRef` equivalent (`resolver.py:178`, `graph.py:117`).
- Only constructor injection exists; no property injection, no lazy module
  loading, no scope bubbling (NestJS makes a singleton that depends on a
  request-scoped provider request-scoped; Bustan errors, which is defensible
  but undocumented in `docs/COMPARISONS.md`).

Fix: document each gap in `COMPARISONS.md` and `TROUBLESHOOTING.md`; validate
`inject` entries in `normalize_provider`; decide which gaps 2.0 closes.

### 4.9 Request execution order and error contract

These findings sit in the HTTP execution path that drives the container.

#### EX-01 Exceptions raised while building the controller or its providers bypass filters, APP_FILTER and observability

Severity: medium. Category: correctness. Status: Confirmed (critic round).

Where: `src/bustan/platform/http/execution.py:122-145` (controller,
request-scoped providers and pipeline built before the `ExecutionContext` and
before `observability.start_request`), `execution.py:185-194` (the except
branch only runs `handle_exception` when both a context and a resolved
pipeline exist; otherwise it logs and returns a hard-coded 500),
`src/bustan/pipeline/filters.py:167-172` (the problem-details mapping that is
skipped), `tests/integration/platform/test_exception_filters.py:80-103` (pins
the 500).

Evidence: `repros/evidence/EX-01.py`: `BadRequestException in request-scoped
ctor -> status=500 ... filter_calls=0 metrics_records=0`; the same exception
raised inside the handler gives `400` problem+json and one metrics record.

Impact: the docs recommend putting the authenticated principal into a
request-scoped provider, which is exactly the code that raises authentication
and validation errors in a constructor; those become opaque 500s that no
filter, `APP_FILTER` or metrics hook ever sees.

Fix: build the context before instantiation (or make the controller lazy on
it), resolve the components that do not depend on the controller first, call
`start_request` before any DI work, and in the except branch fall back to the
global filter chain whenever a context exists; update the pinned test.

#### EX-02 A broken AUTHENTICATOR_REGISTRY wiring is reported as 403 on every request

Severity: medium. Category: API ergonomics. Status: Confirmed (round two).

Where: `src/bustan/pipeline/guards.py:78-84` (resolved per request; every
`ProviderResolutionError` becomes `GuardRejectedError`),
`src/bustan/platform/http/compiler.py:179-180` (the compiler knows which
routes carry an auth policy but validates nothing).

Evidence: `repros/evidence/EX-02.py`: registry declared in a module the
controller module does not import: `create_app` succeeds and every
authenticated route returns `403 Unknown authenticator registry for strategy
'bearer'`; a request-scoped async registry fails the same way.

Impact: a deployment whose auth wiring is broken looks like a client
authentication failure on dashboards and to clients.

Fix: verify at compile time that `AUTHENTICATOR_REGISTRY` is visible from the
module of every route with an auth policy and is resolvable synchronously;
keep the request-time fallback but log the underlying cause at error level.

#### EX-03 The middleware exception path is unguarded

Severity: low. Category: correctness. Status: Confirmed (round two).

Where: `src/bustan/platform/http/execution.py:237-281` (`execute_http_exception`
has only a `try/finally`), `src/bustan/platform/http/adapters/starlette.py:112-115`.

Evidence: `repros/evidence/EX-03.py`: the same DI failure returns
`application/json {"detail": "Internal server error"}` on the route path and
`text/plain Internal Server Error` on the middleware path; with `debug=True`
the middleware path sends a 5987-byte traceback containing resolver frames and
the `ProviderResolutionError` text to the client.

Fix: wrap the body of `execute_http_exception` in the same except block as
`execute_http_route` so both paths share one 500 contract.

#### EX-04 403 responses disclose guard class paths and strategy names

Severity: low. Category: security. Status: Confirmed (round two).

Where: `src/bustan/pipeline/guards.py:105` (`Guard {qualname} blocked the
request`), `guards.py:84` and `:88` (strategy name in the message),
`src/bustan/pipeline/filters.py:141-143` (`str(exc)` copied into the
problem-details `detail`; only 5xx details are masked).

Evidence: `repros/evidence/EX-04.py`: `403 {'detail': 'Guard
__main__.InternalOnlyGuard blocked the request'}` and `"Unknown authenticator
registry for strategy 'acme-hmac-v2'"`, identical with `debug=False`.

Fix: use a generic client-facing detail (`Forbidden`) and keep the guard name
and strategy in a log field or an exception attribute that is not serialized.

### 4.10 Provenance of the second round

The findings marked "round two" came from the test-suite audit and
multi-tenant attacker lenses; those marked "critic round" came from the
completeness critic that re-read the code against the established list.
Both sets went through the same reproducer verification as round one.

## 5. What did not reproduce, and calibrations

Honest negatives matter as much as the findings above.

- Inherited `__init__` with plain class tokens works. The lead auditor's first
  version of RF-03 (a base class in another module whose annotation names a
  visible provider class) resolved correctly, because the synthesized
  namespace rescues bare names. Only marker names, token constants and
  aliases fail. The rescue is itself the mechanism behind RF-01.
- `uv lock --check` passes. The "lock out of sync" sub-claim in QA-08 is
  reduced to "a plain `uv run` rewrites one metadata line".
- Singleton providers (not controllers) that declare a request-scoped
  constructor dependency are rejected, and singleton providers cannot inject
  `Request`. The guard works for the case the tests cover; the findings are
  about the paths around it.
- Eager singleton instantiation under the lifespan is a real, if accidental,
  mitigation for RI-06 and RI-07: those leak only when the lifespan does not
  run. The reproducer calibrated both to medium for that reason. Every test
  suite that uses `TestClient(app)` without a `with` block, and
  `create_app_context` without `init()`, is in the unmitigated case.
- CR-02 (double construction across the sync and async paths) was calibrated
  to low by the reproducer because it needs an uncached shared-scope binding,
  which after startup means a durable provider or an app without a lifespan.
  The lead auditor rates it medium for durable providers because the leaked
  instance is a real resource.
- The `hasattr` `KeyError` (RF-07) and the `__new__` gap (RF-08) are only
  reachable by driving the container directly.
- Existing tests do not lock in the RI-01 behavior: a skeptic monkeypatched
  the guard to drop the controller exemption and the relevant suites passed,
  so the fix does not require changing test expectations.
- Some evidence scripts use internal modules (`bustan.core.*`,
  `bustan.app.bootstrap._create_app(no_lifespan=True)`) where the public
  surface has no equivalent; each such case is noted in the script header and
  a public-surface variant exists wherever one was possible.

## 6. Maintenance roadmap

Principles: one pull request per root cause; foundational changes first
because several fixes share a mechanism; every fix flips at least one script
in `repros/` from `REPRODUCED` to `FIXED` and lands with the regression test
described in section 7. Effort: S is under a day, M is one to three days, L
is a week or more. "Breaking" refers to the stable surface (`bustan`,
`bustan.errors`, `bustan.testing`); errors that now surface earlier are
intended breaks and are marked as such.

### Phase 0: stop the bleeding (this week)

| Item | Findings | Files | Effort | Breaking |
| --- | --- | --- | --- | --- |
| 0.1 Enforce the owner scope for controllers: pass `ControllerMetadata.scope` into `instantiate_class`, delete the `owner_is_controller` exemptions in the guard and the special-token path, reject singleton controllers that name `Request`, `REQUEST`, `RESPONSE` or a request-scoped binding at `compile_route_contracts`, reject durable controllers | RI-01, RI-05, RI-09, RI-10 | `core/ioc/resolver.py`, `platform/http/controller_factory.py`, `platform/http/compiler.py` | M | Intended: leaking apps now fail at `create_app` |
| 0.2 One effective-scope rule at container build time: `use_existing` inherits its target's scope, a factory's scope must be at least as strict as every `inject` token's, `use_class` defaults to the class's declared scope, singleton and durable owners may not reach request scope, singletons may not reach durable scope; `ApplicationContext.get` and `ModuleRef.get` clear the active request | RI-02, RI-03, RI-06, RI-07 | `core/ioc/registry.py`, `core/ioc/container.py`, `core/ioc/resolver.py`, `app/application.py`, `addons/module_ref.py` | M | Intended: scope errors surface at bootstrap with the documented message |
| 0.3 Durable scope containment: no `Request` injection into durable owners (pass the durable key instead), bounded store with `evict_durable` and `clear_durable`, per-key locks released after construction, key computed once and validated hashable, `on_module_destroy` on eviction and at shutdown | RI-04, CR-01, CR-06, OL-12 | `core/ioc/resolver.py`, `core/ioc/scopes.py`, `core/ioc/container.py`, `core/lifecycle/runner.py`, `docs/` | M | Yes for durable providers that inject `Request` (rare); document the migration |
| 0.4 Guards before construction: resolve and run guards before instantiating the controller, request-scoped providers and durable partitions; evict partitions created by a rejected request; give `get_durable_context_key` an authenticated context; generate `request_context_id` once per request | RI-11, RI-12 | `platform/http/execution.py`, `pipeline/guards.py`, `addons/context.py`, `core/ioc/scopes.py` | M | Intended: constructors no longer run for rejected requests |
| 0.5 Disclosure and release: security advisory for RI-01 through RI-05 (cross-request identity disclosure in 1.1.0), `CHANGELOG.md` entry, 1.1.1 release once 0.1 to 0.3 land; until then update `docs/REQUEST_SCOPED_PROVIDERS.md` and `docs/TROUBLESHOOTING.md` to say the controller rule is not enforced | RI-01 | `SECURITY.md`, `CHANGELOG.md`, `docs/` | S | No |

### Phase 1: correctness and hardening (two to six weeks)

| Item | Findings | Files | Effort | Breaking |
| --- | --- | --- | --- | --- |
| 1.1 Constructor plan cache and bootstrap validation: plan every class binding and controller once per `(class, module, scope)` at container build, verify every non-special, non-optional token is visible, report all failures together from `create_app` and `create_app_context` | CR-05, MG-04, RI-09 | `core/ioc/resolver.py`, `core/ioc/container.py`, `app/bootstrap.py` | M to L | Intended: broken graphs fail at bootstrap |
| 1.2 Annotation resolution order: evaluate hints with the constructor's own `__globals__` (computed lazily), consult the synthesized namespace only for otherwise-undefined names and raise on same-name ambiguity, unwrap `Optional` and `X \| None`, honor parameter defaults, reject duplicate `Inject` markers, wrap every introspection failure, allow `Request` for transient owners inside a request | RF-01, RF-02, RF-03, RF-04, RF-09, RF-11, RI-14 | `core/ioc/resolver.py` | M | Intended: hijacked annotations now raise; `OptionalDep` with a default now yields the default |
| 1.3 Provider normalization hardening: read metadata from `__dict__`, store a frozen `ProviderMetadata`, sentinel-based cache misses, dict shape validation (one `use_*` key, no stray `inject`, callable and class checks, no string `inject`), translate `ValueError` and hashability failures into `InvalidProviderError`, reject sets and bare dicts in `@Module`, require a valid key hook for durable bindings, type-aware canonical token keys | PN-01, PN-02, PN-04, PN-06, PN-07, PN-10, PN-11, MG-10 | `common/decorators/injectable.py`, `core/ioc/registry.py`, `core/ioc/scopes.py`, `core/module/compiler.py`, `core/module/decorators.py` | M | Small: invalid definitions that used to fail late now fail at import or bootstrap |
| 1.4 One visibility source: compute token to declaring module per node in `build_module_graph` (including global exports and re-export origins), copy it into the registry, derive `available_providers` and export validation from it, raise on colliding exports, give module-class exports a targeted error or implement module re-export | MG-01, MG-02, MG-03, MG-07 | `core/module/graph.py`, `core/ioc/container.py`, `core/ioc/resolver.py` | M | Intended: ambiguous graphs now fail at bootstrap |
| 1.5 Override semantics: make overrides bootstrap-only (register before startup, raise after) or dependency-aware (evict transitive dependents), resolve `APP_*` providers lazily per request with list bindings, accept a module class or `DynamicModule` as the override target, use equality-consistent token lookup, run hooks on override instances | OL-01, OL-02, OL-06, OL-07, PN-03 | `core/ioc/container.py`, `core/ioc/overrides.py`, `platform/http/compiler.py`, `platform/http/controller_factory.py`, `testing/` | M to L | Yes for `bustan.testing` users who override after startup; document the new rule |
| 1.6 `bustan.testing` delegates to `LifecycleManager`: `compile()` calls `startup()`, `close()` calls `shutdown()`, replacements are built from the declaring module through the async paths, partial teardown on startup failure, `ExceptionGroup` for aggregated errors, hooks dispatched only to constructed instances, decide the post-shutdown contract | OL-03, OL-04, OL-05, OL-08, OL-13, OL-14 | `testing/builder.py`, `core/lifecycle/manager.py`, `core/lifecycle/runner.py`, `app/lifespan.py` | M | Small: `close()` now runs `before_application_shutdown` |
| 1.7 Request-aware resolution and a single `APPLICATION` contract: push the native request for the whole route execution including route middleware, clear request state at the outermost boundary, add `ModuleRef.get(token, request=...)` or `ExecutionContext.resolve`, normalize `APPLICATION` to the Bustan application on every path so the addons work under `ApplicationContext`, push the application during startup, fix the `hasattr` fallback, let inject lists name the special tokens | OL-11, RF-05, RF-06, RF-07, RF-10, RI-13, PN-09 | `platform/http/execution.py`, `addons/module_ref.py`, `core/ioc/resolver.py`, `core/lifecycle/manager.py` | S to M | No |

| 1.8 One error contract for the request path: build the execution context and start observability before any DI work, route setup failures through the filter chain, guard the middleware exception path, use a generic `Forbidden` detail, validate `AUTHENTICATOR_REGISTRY` visibility at compile time | EX-01, EX-02, EX-03, EX-04 | `platform/http/execution.py`, `platform/http/compiler.py`, `pipeline/guards.py`, `pipeline/filters.py` | M | Small: setup failures now get mapped statuses instead of 500 |
| 1.9 Make the test suite tell the truth: `precision = 2` on the coverage gate plus a kernel-specific gate, convert the six defect-pinning tests to strict `xfail`, rewrite the resolver seam tests as black-box tests, add the untested categories (provider hook failures, override by scope, durable over HTTP, dynamic-module overrides) | QA-11, QA-12, QA-13, QA-14, QA-15, QA-16 | `pyproject.toml`, `tests/**` | M | No |

### Phase 2: architecture and maintainability (one quarter)

| Item | Findings | Files | Effort | Breaking |
| --- | --- | --- | --- | --- |
| 2.1 Collapse the resolver twins: one planning core with sync and async drivers, a single construction-state machine per key, the request-time path async so request and transient async factories work, one `Binding.is_async` predicate, coroutine closed on error | QA-02, CR-02, CR-03, CR-04, OL-09, OL-10 | `core/ioc/resolver.py`, `core/ioc/scopes.py`, `platform/http/execution.py`, `platform/http/controller_factory.py` | L | No for the public surface; internal API changes |
| 2.2 Layering: move route validation into the platform compiler, make framework-owned types adapter-supplied (including `HttpRequest`), give `ModuleKey` a real type, declare `ContextVar`s once | QA-01, QA-07, QA-10 | `core/module/graph.py`, `core/ioc/*`, `platform/http/*`, `core/utils.py` | M | No |
| 2.3 Typing and encapsulation: tagged `Binding` union, overloads so `get(InjectionToken[T])` returns `T`, read-only views of registry and caches, `eq=False` on frozen nodes | QA-05, QA-06, PN-08 | `core/ioc/registry.py`, `app/application.py`, `core/ioc/container.py`, `core/ioc/tokens.py` | M | Yes for code that mutates internals |
| 2.4 Module identity and dynamic modules: value-based `DynamicModule` identity with stable instance ids, single module instantiation with constructor injection, dynamic providers overriding base tokens, cycle paths through dynamic modules, `imports` on `for_root_async` | MG-05, MG-06, MG-08, MG-09, DP-02 | `core/module/*`, `pipeline/middleware.py`, `core/lifecycle/runner.py` | M | Small: equal registrations now share one instance |
| 2.5 Formatting, lint and repository hygiene: one `ruff format` commit in `.git-blame-ignore-revs`, `ruff format --check` in CI and lefthook, a real lint rule set, dead code and stale comments removed, workspace table removed, `fail_under` moved to the CI command, `uv lock --check` in CI | QA-03, QA-04, QA-08 | `pyproject.toml`, `.github/workflows/ci.yml`, `lefthook.yml`, `core/**` | S | No |

### Phase 3: feature parity and 2.0 readiness

| Item | Findings | Effort | Breaking |
| --- | --- | --- | --- |
| 3.1 Request-scoped and transient async providers plus per-request disposal (an `on_request_end` hook or async context manager support) | OL-09 | L | No |
| 3.2 Multi-binding `APP_*` tokens and request-scoped global guards, interceptors and filters | OL-02 | M | No |
| 3.3 `ModuleRef` host-module scoping, `strict=False` as a container-wide lookup, `INQUIRER` as the requesting instance | DP-01, DP-03, RI-08 | M | Yes: documented semantics change |
| 3.4 Module re-export, `forwardRef`-style deferred references, optional `inject` entries; explicit decisions and documentation for property injection, lazy modules and scope bubbling | MG-07, DP-03 | L | No |
| 3.5 Durable scope redesign around an explicit context-id strategy, with bounded stores and disposal as first-class concepts | RI-04, CR-01 | L | Yes for durable providers |
| 3.6 Public API freeze for 2.0: promote a typed `Container` facade, remove `Any` from `ApplicationContext`, regenerate the API reference and the comparison guide | QA-05 | M | Yes by design |

### Quick wins (under an hour each)

- Sentinel-based cache misses (PN-02).
- `scope.get("app")` instead of `hasattr` (RF-07).
- Raise on a second `Inject` marker (RF-09).
- Translate `ValueError` from scope coercion and check token hashability (PN-06).
- Compute the durable key once per resolve (CR-06).
- Delete `FRAMEWORK_OWNED_TYPES`, `ResolvedT`, the unreachable `str` branch and the narrative comments (QA-04).
- Remove the `mini` workspace member; add `ruff format --check` and `uv lock --check` to CI (QA-08, QA-03).
- Rewrite the `ApplicationContext.get` docstring so it stops pointing at `app.resolve()` (OL-11).
- Add the override caveat to the README until 1.5 lands (OL-01).
- Correct `docs/REQUEST_SCOPED_PROVIDERS.md` and `docs/TROUBLESHOOTING.md` about singleton controllers until 0.1 lands (RI-01).
- Name the token, not `type`, in provider hook errors (OL-04).
- Generate `request_context_id` from `uuid4` stored on `request.state` (RI-12).
- Set `precision = 2` on the coverage gate (QA-11).
- Drop or wire the lifecycle `signal` parameter (OL-16).
- Generic `Forbidden` detail for guard rejections (EX-04).

## 7. Testing strategy

The suite is good at asserting what the container does on the happy path and
silent about what it must never do. Add these categories, each mapped to the
findings it guards:

1. Request isolation matrix (RI-01 to RI-09, RI-02): for every owner scope
   (singleton controller, request controller, transient controller, singleton
   provider, transient provider, durable provider) and every request-derived
   dependency (request-scoped provider, `Request`, `RESPONSE`, `INQUIRER`,
   durable provider, factory `inject`, `use_existing` alias, imperative
   `app.get`), send two requests with different identity headers and assert
   either a bootstrap error or full isolation. Run the matrix twice: with the
   lifespan and without it.
2. Bootstrap validation (MG-04, MG-01, MG-02, PN-01): graphs with a missing
   dependency on a transient, request-scoped or controller edge, a re-export,
   a colliding export and an undecorated subclass must fail at `create_app`.
3. Annotation resolution (RF-01 to RF-04, RF-09): base classes in separate
   modules, same-named classes across modules, `Optional` and unions, defaults,
   `OptionalDep` with defaults, duplicate markers; run under
   `from __future__ import annotations`.
4. Override contract (OL-01, OL-02, OL-06, OL-07, PN-03): transitive
   dependents, `APP_*` tokens, dynamic module targets, runtime-built string
   tokens, lifecycle hooks on replacements; assert whichever rule 1.5 chooses.
5. Lifecycle (OL-03, OL-05, OL-13, OL-14, OL-15, OL-04): `bustan.testing`
   against `LifecycleManager` for the same graph, partial teardown after a
   failed bootstrap, hook order including async factories, value providers
   excluded from hooks, aggregated errors carrying causes.
6. Concurrency (CR-01 to CR-04): durable growth under distinct keys with an
   asserted bound, mixed sync and async resolution under `anyio`, threads and
   task groups inside one request, event-loop stall detection with a heartbeat
   task.
7. Normalization property tests (PN-04, PN-06, MG-10): generate dict
   providers with random key sets and assert every invalid shape raises
   `InvalidProviderError` naming the module and key.
8. Coverage gate per package: `bustan.core.ioc` at 95 percent branch coverage
   on its own, so the async twin paths cannot regress unseen (QA-09), with
   `precision = 2` so the global gate compares honestly (QA-11).
9. Execution order and error contract (RI-11, RI-13, EX-01 to EX-04): a
   request-scoped provider that raises `BadRequestException` in its
   constructor maps to 400 through the filter chain; a guard rejection runs no
   constructors; middleware shares the request scope; both 500 paths return the
   same JSON body; 403 bodies carry no class names.
10. Truthful suite (QA-12, QA-13, QA-14, QA-16): the six defect-pinning tests
    become strict `xfail`s stating the intended behavior; resolver behavior is
    asserted through the public API; provider hook failures and lifecycle
    re-entrancy are covered; one request factory lives in `conftest.py`.

Convert every script in `repros/` into one of these tests as its finding is
fixed; `run_repros.py --expect-fixed` can guard the transition in CI until the
directory is empty.

## 8. Process and tooling

- Security: treat RI-01 through RI-05 as a coordinated disclosure under
  `SECURITY.md`; state the affected version (1.1.0 and the unintended 1.0.x)
  and the fixed version; add the two-request isolation tests to the release
  checklist.
- CI: add `ruff format --check`, `uv lock --check`, `precision = 2` on the
  coverage gate, a per-package coverage threshold for `bustan.core.ioc`, and a
  job that runs the examples both with and without the lifespan.
- Repository hygiene: remove the dangling workspace member, move
  `fail_under` to the CI command line so targeted runs stay green, list the
  formatting commit in `.git-blame-ignore-revs`, align the `ty` paths between
  CI and lefthook.
- Documentation: every rule the container enforces should have a sentence in
  the docs and a test; every rule the docs state should be enforced. The
  three contradictions found here (RI-01, OL-05, OL-11) all sit on that seam.
- Versioning: the alpha stability guide already reserves the right to change
  internals; use it to land 2.1 and 2.3 before 2.0 rather than after.

## Appendix A: running the repros

```bash
uv sync --group dev --frozen
uv run python docs/audits/di-container-2026-09/run_repros.py            # summary table
uv run python docs/audits/di-container-2026-09/run_repros.py --verbose  # full output
uv run python docs/audits/di-container-2026-09/run_repros.py --expect-fixed  # regression gate
uv run python docs/audits/di-container-2026-09/repros/evidence/RI-01.py  # one evidence script
```

Each script in `repros/` prints `RESULT: <id> REPRODUCED|FIXED|ERROR - <message>`
per sub-finding. A `FIXED` line means the fix landed: convert the script into
a regression test and delete it. `ERROR` means the script itself broke (an API
rename, a missing dependency); fix the script before trusting the run.
`repros/evidence/` holds the verbatim verification scripts from the audit,
described in its README. VS Code launch configurations for the IoC unit tests
and for the repro scripts are in `.vscode/launch.json`.

## Appendix B: audit lenses

The questions each pass asked, kept here so the audit can be repeated on a
future revision.

1. Request isolation: does every path that can inject request-derived state
   check the owner's scope (constructor parameters, factory `inject` lists,
   `use_existing` aliases, `Request`, `RESPONSE`, `APPLICATION`, `INQUIRER`,
   durable providers)? Is anything constructed lazily on the first request and
   cached for the process lifetime? Does the active request leak into nested
   resolutions? Test with two requests carrying different identities.
2. Concurrency and resources: which dicts of locks or instances only grow?
   Which keys are attacker-controlled? Can two paths build the same shared
   instance? Are locks held while user code runs? Is reflection repeated per
   instantiation?
3. Module graph: is visibility computed in one place? What is accepted by the
   graph and unresolvable by the container? How are global, dynamic and
   re-exported tokens keyed?
4. Provider definitions: what does `normalize_provider` ignore silently?
   Which metadata is inherited by subclasses? Which values are cache
   sentinels?
5. Constructor reflection: which globals evaluate string annotations? What
   takes precedence when names collide? Are unions, defaults and markers
   handled?
6. Overrides and lifecycle: what survives an override? What is eager, what is
   lazy, and which failures does the lifespan mask? Which objects receive
   hooks?
7. Code quality: formatting, duplicated paths, layering, typing at the public
   boundary, dead code, configuration drift.
8. Documentation and parity: execute every documented claim; list what a
   NestJS developer would expect and does not get.

## Appendix C: coverage baseline

| File | Statements | Missed | Branches | Partial | Coverage |
| --- | --- | --- | --- | --- | --- |
| `core/ioc/resolver.py` | 406 | 25 | 154 | 15 | 92 percent |
| `core/ioc/scopes.py` | 104 | 4 | 24 | 6 | 92 percent |
| `core/ioc/overrides.py` | 40 | 2 | 8 | 0 | 96 percent |
| `core/ioc/container.py` | 66 | 0 | 26 | 1 | 99 percent |
| `core/ioc/registry.py` | 48 | 0 | 14 | 0 | 100 percent |
| `core/lifecycle/hooks.py` | 24 | 5 | 0 | 0 | 79 percent |
| `core/lifecycle/manager.py` | 58 | 5 | 20 | 3 | 90 percent |
| `core/lifecycle/runner.py` | 90 | 9 | 30 | 1 | 90 percent |
| `core/module/graph.py` | 141 | 7 | 40 | 4 | 94 percent |
| `testing/builder.py` | 98 | 1 | 12 | 1 | 98 percent |

Measured with `uv run pytest tests --cov=bustan.core.ioc --cov=bustan.core.module
--cov=bustan.core.lifecycle --cov=bustan.testing --cov-report=term-missing`
at commit `0cfe6dc`.
