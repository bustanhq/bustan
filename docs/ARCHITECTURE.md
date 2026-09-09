# Architecture

This document is for the next person to change `src/bustan`. It states how the package
is layered, why an import that crosses a layer the wrong way is a defect rather than a
style preference, and how CI fails a build that adds one.

Read it before you add a dependency between two packages. The rule is cheap to respect
while you are writing the import and expensive to unwind afterwards, and the reason it
exists at all is that the last time nothing objected, a web framework reached 56
references across 23 files including the injection kernel.

## The Layers

Every top-level package under `src/bustan` belongs to exactly one layer. A package may
import its own layer and any layer below it, and never a layer above it.

```bash
uv run python scripts/check_layering.py --layers
```

| Rank | Layer | Packages | May import a web server |
| --- | --- | --- | --- |
| 0 | `contracts` | `contracts` | no |
| 1 | `kernel` | `common`, `kernel` | no |
| 2 | `runtime` | `observability`, `pipeline`, `runtime` | no |
| 3 | `adapters` | `adapters` | **yes** |
| 4 | `application` | `addons`, `app`, `cli`, `configuration`, `health`, `openapi`, `security`, `testing`, and the modules directly under `src/bustan` | no |

The table in `scripts/check_layering.py` is the definition, not this document. A
contributor who adds a top-level package declares its layer there, and the check fails
with that instruction until they do, so the table cannot be bypassed by forgetting it
exists.

### What Each Layer Is For

**`contracts`** is the vocabulary the framework and its transport adapters share: the
adapter port, the neutral request and response types, and the values they carry. It
imports nothing from the rest of `bustan` and nothing from any web framework. That
one-way dependency is what lets an adapter be written against a declaration rather than
against framework internals, and it is why installing `bustan` requires no server
library at all.

**`kernel`** is injection, modules, lifecycle, and the decorators the kernel reads its
metadata from. It is the part of the framework that has nothing to do with HTTP. A
kernel that imports the runtime is a kernel that cannot be used without one.

**`runtime`** is neutral request execution: the stages a request runs through, the
pipeline components that sit on it, and the observability it emits. `pipeline` and
`runtime` import each other at module scope, so neither can be ordered below the other
until that is untangled; they share a rank rather than pretending to an order they do
not have. `observability` sits with them because a span and a metric are emitted from
the request path and by nothing below it.

**`adapters`** is the only layer permitted to import a web server, and the rule is
enforced by name against a denylist of web frameworks and servers rather than by an
allowlist of permitted dependencies, because the coupling being caught is about web
servers specifically. Two adapters ship: one over Starlette, one written against the
ASGI specification and the standard library alone. Both are held to the same answers by
`scripts/conformance_matrix.py`.

**`application`** is everything assembled on top: bootstrap, configuration, the
security policy decorators, OpenAPI, the CLI, the testing surface, and the health and
readiness probes. `health` belongs here rather than lower down because it is an
application in miniature - it declares a controller and a module, and its controller
carries the throttling decorator `security` owns - so a package that reached down to
it would be reaching into an application, not into the framework.

## Why The Direction Matters

Three consequences, each of which was a real defect before the rule existed:

- **The kernel must be usable with no web server installed.** `scripts/package_smoke_check.py`
  proves that in a clean environment. It stops being true the moment something below
  the adapter layer imports a transport, and it stops being true silently, because the
  development environment always has one.
- **A second adapter must be possible without touching framework code.** If the runtime
  reaches into a specific adapter, the port is not the seam; the adapter is. The proof
  that the seam is real is that a second adapter exists and passes the same conformance
  matrix.
- **The direction is what makes a package testable on its own.** A cycle between two
  layers means neither can be read without the other, and the audit that started this
  work found exactly that shape wherever it looked.

## The Check Is A Gate

`scripts/check_layering.py` reports every import that crosses a layer the wrong way and
every top-level package the table does not declare. Run it before you push:

```bash
uv run python scripts/check_layering.py
```

CI runs the same command in the `Package layering` job, and that job blocks. A report
that is not empty stops the merge, and the crossed boundary is quoted on the run
summary so a red job says what it objected to without anyone opening a step log.

**A violation is closed by moving the import, never by weakening the check.** Not by
declaring a package into whichever layer makes its existing imports legal, not by
widening the web-server denylist, not by adding a directory to the non-source
exclusions, and not by moving the import under `TYPE_CHECKING`. The check counts
deferred imports on purpose: a function-local or type-checking import is still a
dependency of the file that writes it, and excluding it would make deferral the way
around the rule. Declaring a genuinely new package is the one table edit that is not a
weakening, and it is only that while the package's own imports already point downward.

The rule the gate enforces is narrow, and the reason it is worth a job of its own is in
the section above: the direction is what keeps the kernel usable with no web server
installed, keeps a second adapter possible without touching framework code, and keeps
each package readable on its own.

## How The Report Was Emptied

This section is history, kept because the shape of these fixes is the shape the next
one should take. The check was written alongside a tree that did not pass it: ten
findings, nine crossing imports and one package the table did not know about. Every
crossing import was closed by moving code; the table gained one entry, for the package
that had never been classified at all.

| What crossed | How it was closed |
| --- | --- |
| `application` imported a web server, in `enable_cors` | A cross-origin policy became the transport adapter's work. Each adapter enforces `CorsOptions` through its own middleware, and `contracts` holds the option type both read. |
| `kernel` imported `runtime` | The controller metadata accessors moved below the request path, so the module graph reads metadata without reaching up into the runtime. |
| `runtime` imported `adapters`, twice, and `application` | The conformance suite moved to the application layer, where naming both shipped adapters and assembling applications through `app.bootstrap` is what the layer is for. |
| `runtime` imported `application`, from four places | The runtime names protocols where it had named application types: route compilation takes a `PipelineOverrides` shape rather than the testing registry, and the request path recognises an application by the `ApplicationRuntime` declaration rather than by its class. |
| `src/bustan/health` had no layer | Declared as `application`, for the reason given under `application` above. |

The last of those emptied the report, and `continue-on-error` came off the CI step in
the same change.

## Where The Rest Of The Architecture Is Written

This document covers layering and nothing else, because layering is the constraint a
contributor can break without noticing. The rest is spread across the guides that own
each part:

- [STABILITY.md](STABILITY.md) - what is public, what is internal, and which side
  derives from which. It is the authority; the `__all__` tuples derive from it.
- [PLATFORM_INTEGRATION.md](PLATFORM_INTEGRATION.md) - the adapter port, and what an
  adapter has to implement.
- [REQUEST_PIPELINE.md](REQUEST_PIPELINE.md) - the order a request runs through guards,
  pipes, interceptors and filters.
- [REQUEST_SCOPED_PROVIDERS.md](REQUEST_SCOPED_PROVIDERS.md) - the scope rules the
  container enforces, and why an owner may not outlive what it injects.
- [LIFECYCLE.md](LIFECYCLE.md) - startup and shutdown ordering.
- [BENCHMARKS.md](BENCHMARKS.md) - what the framework costs, and the gate that fails a
  regression.
- [OBSERVABILITY.md](OBSERVABILITY.md) - what the runtime emits, and the two protocols
  it emits through.
