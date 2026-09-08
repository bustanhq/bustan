# Architecture

This document is for the next person to change `src/bustan`. It states how the package
is layered, why an import that crosses a layer the wrong way is a defect rather than a
style preference, why the check that finds those imports does not currently fail the
build, and which violations are open right now.

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
| 4 | `application` | `addons`, `app`, `cli`, `configuration`, `openapi`, `security`, `testing`, and the modules directly under `src/bustan` | no |

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
security policy decorators, OpenAPI, the CLI, the testing surface.

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

## Why The Check Is Advisory

`scripts/check_layering.py` exits `1` on this tree. CI runs it under
`continue-on-error: true`, writes the report to the run summary, and stays green.

That is deliberate and it is temporary. The violations the check reports are defects to
close, not entries to add to the table, and no violation is closed by weakening the
check: not by adding a package to the layer table, not by widening the web-server
denylist, and not by moving an import under `TYPE_CHECKING`. The check counts deferred
imports on purpose, because a deferred import is still a dependency and excluding them
would make deferral a way around the rule.

Making it blocking today would either fail every pull request or force whoever is
holding the pager to legalise the existing edges. So the arrangement is: the report is
visible on every run, and `continue-on-error` comes off the moment the report is empty.
The comment on the CI step says the same thing, and it is the instruction to follow:

> Delete `continue-on-error` the moment the report is empty: an advisory layering check
> that stays advisory is a layering check nobody reads.

An advisory check has one honest failure mode - nothing objects to a new violation - so
treat the report as blocking yourself. **Run it before you push and compare it against
what it said before your change.** A report that grew is a change to reconsider, whether
or not CI agrees.

## The Open Violations

Measure them; do not read a number out of this document. Line numbers in particular
move on almost every merge, so what is recorded here is the count and the edges.

```bash
uv run python scripts/check_layering.py
```

On the commit this document was written against, the report holds **nine import
violations plus one unclassified package**:

| What | Where | Why it is a violation |
| --- | --- | --- |
| Unclassified package | `src/bustan/health` | Landed after the layer table was written and nobody declared it. |
| `application` imports a web server | `app/application.py`, in `enable_cors` | `starlette.middleware.cors` reaches the application layer; the only violation with a user-visible symptom. |
| `kernel` imports `runtime` | `kernel/module/graph.py` | The module graph reads controller metadata out of the runtime, so the kernel cannot be read without it. |
| `runtime` imports `adapters` | `runtime/conformance.py`, twice | The conformance suite lives in `runtime` and names both shipped adapters. |
| `runtime` imports `application` | `runtime/conformance.py` | The same suite assembles applications through `app.bootstrap`. |
| `runtime` imports `application` | `runtime/controller_factory.py`, `runtime/execution.py`, `runtime/routing.py` | Three modules reach for `testing.overrides` to find pipeline overrides. |
| `runtime` imports `application` | `runtime/execution.py` | The execution engine names `app.application`. |

Eight of the ten have no user-visible symptom: they are import direction, and the cost
they carry is that the packages cannot be read, tested or reused apart. The CORS one is
the exception, and it is why an application that never enables CORS still cannot serve
without Starlette installed on that path.

Closing them is tracked in [issue 197](https://github.com/bustanhq/bustan/issues/197)
and its five children. The last of those classifies `health`, empties the report and
deletes `continue-on-error`; that is the commit after which this section is a history
note rather than a to-do.

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
