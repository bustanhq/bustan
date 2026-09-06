# Audit lenses for the bustan DI container

Each lens lists the questions to answer and the code that answers them. Line
numbers drift; search for the symbol names.

## Lens 1: request isolation and scope leaks (critical tier)

Code: Resolver._guard_request_scoped_dependency, Resolver._resolve_special_token,
Resolver.call_factory, Resolver._resolve_binding (use_existing),
ControllerFactory.instantiate, Container._build_bindings.

- Does every path that can inject request-derived state check the OWNER's scope?
  Constructor parameters, factory inject lists, use_existing aliases, the
  Request/RESPONSE/APPLICATION special tokens, durable providers.
- Are controllers treated as request-safe just because they are controllers?
  A default-scope controller is a singleton cached in
  ScopeManager.controller_singletons.
- Is anything constructed lazily on the first request and then cached for the
  process lifetime (singletons built without the lifespan, controllers, durable
  instances)?
- Does the active_request ContextVar leak into nested resolutions that pass
  request=None?
- Do overrides, request caches or durable caches survive longer than their
  owner?

Test shape: two TestClient requests with different identity headers; assert
the second never observes the first.

## Lens 2: concurrency, locks and resource growth (high tier)

Code: ScopeManager (every dict of locks or instances), Resolver.resolve vs
Resolver.resolve_async (threading.Lock vs anyio.Lock), Resolver._cache_instance.

- Can two paths construct the same shared instance twice? What happens to the
  discarded instance (no lifecycle hooks run on it)?
- Which keys are attacker-controlled (durable context keys derived from
  headers)? Is anything ever evicted?
- Are locks held while user code runs? Can user code re-enter the container
  from another thread?
- Is the reflection work (inspect.signature, get_type_hints, namespace
  synthesis over every visible token) repeated per instantiation?
- Are ContextVars visible inside anyio.to_thread workers?

## Lens 3: module graph and binding visibility (high tier)

Code: build_module_graph, expand_module_input, validate_module_compiled,
Container._build_bindings, Resolver._get_declaring_module, _validate_exports.

- Two sources of truth: ModuleNode.available_providers (graph) versus
  Registry.module_visibility (container). Any token accepted by one and not
  resolvable by the other is a bug (re-exports).
- Global modules: duplicate exports, first-wins ordering, re-exports.
- Dynamic modules: identity versus equality, instance ids, the same object
  imported twice.
- What is validated at bootstrap versus at first request?

## Lens 4: provider normalization and metadata (high tier)

Code: normalize_provider, Injectable, InjectionToken, Binding.

- Metadata stored as a class attribute is inherited by subclasses via getattr.
- Dict providers: which keys are silently ignored (scope on use_value and
  use_existing, inject on use_class, the class's own declared scope when
  use_class is used)?
- Token hashability and identity; None as a value; falsy values in caches.

## Lens 5: constructor reflection (medium tier)

Code: Resolver._plan_constructor_parameters, _build_type_hint_namespace,
_parse_dependency, _detect_owner_scope.

- get_type_hints globals: the subclass module versus the function's module
  for inherited __init__ under PEP 563 string annotations.
- localns precedence: a visible token with the same __name__ as a class in the
  constructor's own module wins silently.
- Optional, unions, defaults, OptionalDep, multiple Inject markers, INQUIRER,
  APPLICATION type inconsistency (Starlette app versus Application versus
  ApplicationContext).
- Owner scope detection by scanning all bindings for the first match.

## Lens 6: overrides, testing and lifecycle (medium tier)

Code: OverrideManager, Container.override, bustan.testing.builder,
bustan.testing.overrides, LifecycleManager, lifecycle.runner.

- Override after dependents were constructed; override of None; override keys
  for dynamic module instances.
- Eager singleton instantiation at startup versus what is never eager.
- Duck-typed hook dispatch over every cached singleton, including use_value
  objects; hook ordering guarantees; shutdown leaving caches populated.
- No disposal for request, transient or durable instances.

## Lens 7: code quality, architecture and typing debt (low tier)

- Formatting (tabs in resolver.py, ruff format not enforced), duplicated
  sync/async paths, stringly-typed resolver_kind, untyped Binding.target,
  ModuleKey union with duck-typed helpers, core depending on platform and on
  Starlette types, unused symbols, leftover narrative comments, public mutable
  registries, Any and object at the public boundary, private attribute access
  from bustan.testing, dangling config (uv workspace member).

## Lens 8: documentation drift and NestJS parity (low to medium tier)

- Extract every DI claim in README.md, docs/REQUEST_SCOPED_PROVIDERS.md,
  docs/LIFECYCLE.md, docs/TROUBLESHOOTING.md and docs/API_REFERENCE.md and
  execute it.
- Parity: forwardRef, module re-export, Optional defaults, multiple APP_* tokens,
  request-scoped global pipeline providers, request-scoped disposal, ModuleRef
  strict semantics, INQUIRER returning a class.
