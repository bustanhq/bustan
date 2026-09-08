# Stability Guide

This guide says what `bustan` promises not to break, what it reserves the right to
change without notice, and how a symbol moves from the second group to the first. The
release the promises attach to is the `version` field in `pyproject.toml`; versions
`1.0.0` and `1.0.1` were released unintentionally during CI/CD setup and should be
treated as early alpha orphans.

## Supported Public Surface

Compatibility commitments apply to three modules only:

- `bustan`
- `bustan.errors`
- `bustan.testing`

Code samples, docs, examples, and changelog guidance should treat those modules as the
supported import surface.

## Which Side Derives From Which

**This guide is the authority, and the `__all__` tuples derive from it.** A symbol is
supported when this guide says it is, and the way that decision is recorded in code is
by naming the symbol in the `__all__` of one of the three modules above. Nothing else
promotes anything: not being importable, not being documented elsewhere, not being
used by an example, and not being reachable through a supported object.

Reading it the other way round is what let the two drift apart. When the export set
was treated as the record of what happened to be exported, a symbol added to `__all__`
in passing became supported without anyone deciding that it should be, and a symbol
this guide described as customisable stayed unexported without anyone noticing that it
was not. Both happened, and neither was visible: the guide and the package could
disagree indefinitely because nothing compared them.

Something does now. `tests/unit/contracts/test_stability_policy.py` fails when this
guide and the package disagree, and it is the reason the two paragraphs above are worth
writing down:

- Every symbol named as supported below is exported from the module named beside it.
- Every `create_app` keyword named below is a real keyword of `create_app`.
- The internal namespace list is exactly the package's own top-level namespaces, minus
  the three supported modules.
- Every supported symbol is defined under a namespace this guide classifies, so a
  namespace that appears in the package without appearing here fails rather than
  passing unclassified.

`tests/unit/test_public_api.py` pins `bustan.__all__` as a tuple in exact order, and
`tests/unit/public_api/` does the same for `bustan.errors` and `bustan.testing`. Those
tests are where the export set is recorded name by name; this guide states the policy
those names are derived from, and does not repeat the list.

## Supported Extension Points

These are the seams an application is expected to customise. Each is supported: the
symbols are exported, their behaviour is documented, and they do not change without a
deprecation window.

| Extension point | Supported symbols | How an application installs one |
| --- | --- | --- |
| Transport adapter | `AbstractHttpAdapter`, `AdapterCapabilities`, `AdapterRoute`, `AdapterRuntime` | `create_app(adapter=...)`, with either a built adapter or a callable the framework calls with an `AdapterRuntime` |
| Authentication strategy | `Authenticator`, `Principal`, `AUTHENTICATOR_REGISTRY` | a provider bound under `AUTHENTICATOR_REGISTRY`, mapping each strategy name to an authenticator |
| Client-visible error payload | `ProblemDetailsExceptionFilter`, `ProblemDetails` | a subclass registered with `UseFilters`, or a provider bound under `APP_FILTER` |
| Route policy | `Auth`, `Public`, `Roles`, `Permissions`, `RateLimit`, `Cache`, `Idempotent`, `Audit`, `Owner`, `DeprecatedRoute` | written on a controller class or on a handler |
| Response serialization | `ResponseSerializer` | nothing yet installs one; see the note below |
| Observability | `ObservabilityHooks`, `MetricsSink`, `RequestTracer` | `create_app(observability=...)` |
| Request limits | `RequestLimits` | `create_app(request_limits=...)` |

Two shapes appear in that last column, and which one an extension point takes is not a
matter of taste:

- **A value the application passes** reaches the framework as a keyword on
  `create_app`. It is one keyword per configuration point, and the setter that seats
  the value on the assembled application stays internal, so there is exactly one
  supported way in and it is visible at the place the application is built.
- **A contract the application implements** needs no keyword. An adapter, an
  authenticator, an exception filter and a policy decorator are each installed by
  writing something and pointing the framework at it - through the `adapter` keyword, a
  provider binding, a filter registration, a decorator - so a second mechanism beside
  those would be a second way to say the same thing.

`ResponseSerializer` is exported as a contract you may implement and type against, and
it is the one entry in the table with no way to install one. The framework builds its
own serializer on the request path and takes no replacement, so an implementation of
this protocol has nowhere to go until the keyword that would seat it exists. It is
listed here rather than left out because the contract itself is supported: a serializer
written against it stays valid when the keyword arrives.

## How To Read The API Reference

[API_REFERENCE.md](API_REFERENCE.md) is generated from the stable public modules above.
When it says a symbol is "Defined in ...", that line identifies the implementation
origin for browsing only. It is not a promise that the implementation module is itself
public.

Import supported symbols from `bustan`, `bustan.errors`, or `bustan.testing`, not from
the internal module shown as the implementation source.

## Injection Token Identity

A provider is registered under a token, and resolution, visibility and overrides all have to agree on when two tokens are the same token. The rule is one sentence: **two tokens are the same token when they have the same type and compare equal.**

That has three consequences you can rely on:

- **`InjectionToken` is identity-based.** It defines no `__eq__`, so two tokens are the same only when they are the same object. `InjectionToken("CONFIG")` written twice is two unrelated tokens, and a provider declared under one cannot be resolved, overridden or exported through the other, however identical the two look in an error message. Build each token once, at module level, and import it.
- **A class is a token, and only itself.** A subclass is a different token from its base class, and two classes with the same name in different modules are two tokens.
- **An equal value of another type is a different token.** `"db"` and a `StrEnum` member whose value is `"db"` compare equal to each other, but they are two tokens: each keeps its own binding, and overriding one never reaches the other. Equal values of the *same* type are one token, so a token computed at runtime resolves and overrides the binding declared with the literal it equals.

What a caller may rely on: the token you write is the token the container matches. The framework never falls back to matching by name, by string value or by class hierarchy, and it never merges two tokens because they happen to compare equal.

Token names carry no meaning to the container. They exist so that errors and the generated API reference can name the dependency, and changing one changes no behaviour.

A token also says what resolving it produces. `app.get(token)` and `app.resolve(token)`
return an instance of the class you asked for, or the `T` of an `InjectionToken[T]`, so
assigning the result to something else is a type error rather than a cast a reader has
to trust. A token that carries no type - a bare string, an enum member - says nothing a
checker can read, and resolving through one is unchecked.

## When A Provider May Be Overridden

An override belongs to bootstrap. It does not stand beside the provider it replaces; it replaces it for the whole application, including every instance already built from it, which is safe only while no request is in flight. The window therefore closes when the application starts, and every later attempt is refused with an error naming the token rather than half honoured.

What that means for the supported testing surface:

- **Register overrides before startup.** `create_test_app()`, `create_testing_module(...).override_provider(...).compile()` and `override_provider()` against an application that has not started all do. A shutdown reopens the window, so an application started, stopped and started again takes a fresh set of overrides on each cycle.
- **`override_provider()` against a running application is refused.** Replacing a provider under a started application cannot reach the singletons startup already built from it, so a block that appeared to swap a dependency would have swapped nothing. The refusal names `create_testing_module(...).override_provider(...)` as the way to write the same test.

## Reading The Container

`app.container` is documented, so what it exposes is worth being explicit about. The
container's own tables - the bindings, what each module can see, which module declares
each controller - and the instance caches behind them are readable through views whose
names end in `_view`: `binding_view`, `visibility_view`, `controller_module_view`,
`singleton_instance_view`, `controller_instance_view` and `durable_instance_view`.

Each is a window rather than a copy, so it reads the container as it stands, and each
refuses a write rather than accepting one. A copy would accept the write and then
discard it, which is worse: the caller is left believing the container changed. The
underlying attributes remain writable because the framework writes them while it builds
the graph; writing them from outside is not supported and the views are how to read
them.

## Internal Modules

Everything outside the three stable modules is internal for compatibility purposes. That sentence is the rule and it is the authority; the list below is the complete set of internal namespaces the package has today, and a test compares it against the top level of `src/bustan/` so it cannot fall behind again:

- `bustan.adapters.*`
- `bustan.addons.*`
- `bustan.app.*`
- `bustan.cli.*`
- `bustan.common.*`
- `bustan.configuration.*`
- `bustan.contracts.*`
- `bustan.health.*`
- `bustan.kernel.*`
- `bustan.observability.*`
- `bustan.openapi.*`
- `bustan.pipeline.*`
- `bustan.runtime.*`
- `bustan.security.*`

Those modules may change names, structure, signatures, or behavior between releases without a deprecation window. A supported symbol is defined in one of them, and that is not a promise about the module it is defined in: import it from `bustan`, `bustan.errors` or `bustan.testing`.

`bustan.testing` is the one top-level namespace absent from that list, because it is one of the three stable modules above. If the package tree gains a namespace and this list has not caught up, the rule decides: it is internal.

## CLI And Scaffold Expectations

The `bustan init` scaffold and the generated package layout are user-facing features, but they are still settling. Treat them as the current recommended workflow, not yet as a frozen long-term compatibility contract.

## Release Expectations

- Public-surface changes are called out in release notes and `CHANGELOG.md`.
- Internal refactors are not described as public compatibility guarantees.
- New examples stay on the stable import surface unless they are explicitly demonstrating an internal maintainer-only concept.

## Promoting A New Public API

Promotion is a decision recorded here first, because this guide is what the export set
derives from. To promote a symbol:

1. Decide it is supported, and say so in this guide: add it to the extension point
   table if it is a seam an application customises, and say how an application
   installs one.
2. If it is a value the application passes rather than a contract it implements, give
   it one keyword on `create_app` and keep the setter that seats it internal.
3. Export it from `bustan`, `bustan.errors`, or `bustan.testing`.
4. Add or update its docstring so the generated API reference is meaningful.
5. Add it to the exact-order tuple in the public-surface test for that module.
6. Regenerate [API_REFERENCE.md](API_REFERENCE.md).
7. Update the guides and examples to use the public import path.

Steps 1, 3 and 5 are three copies of one decision, and the tests named earlier fail
when they disagree, so a promotion that stops halfway is caught rather than shipped.

For the release policy behind this guide, see [VERSIONING.md](VERSIONING.md).
