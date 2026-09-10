# The `bustan` Command Line Tool

Installing `bustan` installs one console script, `bustan`. It scaffolds a project, and it
answers questions about an application you already have: what a codebase still owes the
2.0 release, what a root module compiles to, what configuration it resolved, and which
routes it serves.

Every command that names an application takes it as an import path in the form
`package.module:RootModule`, and it must be importable from the directory you run the
command in.

```
usage: bustan [-h] [--version] {init,governance,routes,doctor,graph,config} ...
```

## Exit Status

| Status | Meaning |
| --- | --- |
| `0` | The command answered, and there was nothing to report. |
| `1` | The command could not answer, or answered with findings that are work to do. |
| `2` | The arguments were not usable, so nothing ran. |

A failure the tool can explain is printed on standard error as one sentence, without a
traceback: a bad import path, a module that does not import, a provider the container
cannot resolve, a file that cannot be read. A traceback out of `bustan` is a defect in
`bustan`, not a message to you.

## `--version`

```bash
bustan --version
```

Prints the installed distribution's version, read from the package metadata of the
environment the command runs in, so it reports what is actually installed rather than
what a source tree says.

## `bustan doctor`

```
usage: bustan doctor [-h] [--format {table,json}] [path]
```

Scans a codebase for constructs 2.0 changed and prints the fix for each one. 2.0 is a
clean break: nothing in the framework accepts a construct it replaced, so an application
written against 1.x fails at import, at build, or at the first request that reaches the
route. This command is what stands in for the compatibility shims the release does not
ship.

`path` defaults to the current directory. A directory is scanned recursively, skipping
virtual environments, caches, build output and version control directories; a single
file is scanned on its own. The scan parses each file rather than importing it, because
the code it is looking for is exactly the code that no longer imports.

The command exits `1` when it finds anything, so it can gate a migration in a pipeline
as well as answer a question in a terminal. A file that cannot be parsed is reported by
name rather than passed over silently, and does not on its own fail the run.

### What it looks for

| Construct | What changed | What to do |
| --- | --- | --- |
| `bustan.core.*` | Renamed to `bustan.kernel.*` | Import the new path. |
| `bustan.platform.http.*` | Renamed to `bustan.runtime.*` | Import the new path. |
| `bustan.logger.*` | Renamed to `bustan.observability.*` | Import the new path. |
| `bustan.config.*` | Renamed to `bustan.configuration.*` | Import the new path. |
| `bustan.adapters.asgi.RequestBodyTooLarge` | No longer exported; an oversized body is answered `413` | Import `RequestBodyTooLargeError` from `bustan.errors`. |
| `ThrottlerStorage.increment`, `ThrottlerStorage.get_ttl` | Replaced by one asynchronous `count_request(key, ttl, limit)` | Rewrite the store against the new method. |
| `MetricsSink.record_request` | Gained a `duration_seconds` keyword | Accept it; a sink without it is still called, but the request is never timed. |
| `TraceSpan.finish` | Replaced by OpenTelemetry's span model | Implement `set_attribute`, `set_status`, `record_exception` and `end`. |
| `RequestTracer.start_span` | Takes `kind`, `attributes` and `context` in place of `labels` | Declare the new signature. |
| `@RateLimit(window=...)` | The window is read where it is written | Write a window the framework can read, such as `60s`, `5m`, `1h` or `1d`. |

Every one of the four renamed packages is internal, so where the symbol you want is
exported from `bustan`, `bustan.errors` or `bustan.testing`, import it from there rather
than from the new internal path. [reference/stability.md](../reference/stability.md) says which those are.

The scan reports only what it can prove from the source. A change that leaves no trace
in the text of a program - a status code that moved, a shutdown that now drains, a body
field that is now checked against its declared type - is in
[CHANGELOG.md](../../CHANGELOG.md) and cannot be found here.

### Output

Under `--format table`, each finding is a block: where it is, what changed, and the fix.

```
src/store/throttling.py:12  ThrottlerStorage.increment
  what changed: ThrottlerStorage declares one asynchronous count_request(key, ttl, limit) in place of increment and get_ttl.
  fix: Replace increment and get_ttl with 'async def count_request(self, key: str, ttl: int, limit: int) -> ThrottleState', counting the request and reporting the key's state in one step, and do not count a request against a window that is already full.

Scanned 34 files: 1 finding in 1 file.
```

Under `--format json` the same scan is one object with `findings`, `skipped` and
`summary` keys, and nothing else is written to standard output, so the whole of it
parses.

## `bustan graph`

```
usage: bustan graph [-h] [--format {table,json}] target
```

Compiles the application and reports the graph behind it: every module with its imports,
controllers, providers and exports, and every provider with the module that declares it,
its scope, how it is resolved, and whether it is exported.

```bash
bustan graph myapp.app_module:AppModule
bustan graph myapp.app_module:AppModule --format json
```

A module built by a factory - anything that returns a `DynamicModule`, including
`ConfigModule.for_root()` - is named by the class it was built from, followed by
`(dynamic)`. It is named rather than described, because what a built module has to say
about itself includes the providers it was built with, and for a configuration module
those are the values it resolved. This command reports the shape of an application and
never its contents.

## `bustan config`

```
usage: bustan config [-h] [--redacted | --no-redacted] [--format {table,json}] target
```

Compiles the application and reports the configuration it resolved, which is what
`ConfigModule.for_root()` registered: the environment files it was given, overlaid with
the process environment. An application that imports no configuration module resolves
none, and the command says so rather than printing an empty table.

**Values are withheld by default.** A key whose name reads as a credential is printed as
`[redacted]`, through the same redaction the framework's own logger uses. Pass
`--no-redacted` to print the values in full, which is a thing to do deliberately and
never into a shared terminal or a captured log.

Two limits are worth knowing before you paste the output anywhere:

- **A credential inside a value is not withheld.** Redaction reads the name of a key, not
  its value, so `JAVA_TOOL_OPTIONS=-Dtrust.password=hunter2` prints in full.
- **The report covers the whole process environment.** Configuration is loaded by
  overlaying the environment onto the files, so every variable the process was started
  with is part of the application's configuration and appears here.

## `bustan init`

```
usage: bustan init [-h] [--force]
```

Writes a Bustan application into the `uv` project in the current directory. It reads the
package name out of `pyproject.toml`, so run it from the project root, and it needs Python
3.13 or newer.

```bash
uv init --package my-service
cd my-service
bustan init
```

Two projects are refused before anything is written, each naming what to do about it. A
directory holding no `pyproject.toml` is not a project yet, and the refusal names the
command that makes one. A manifest declaring no `[build-system]` table is a project `uv`
builds no package from, so neither script this writes would be exposed by it. That is what
the flag in the step above is for: `uv init --package` declares a build system and `uv init`
on its own does not.

### What it writes

Seven files: the entry point, the root module, a controller and a service under
`src/<package>`, and a test for each of the last three under `tests/<package>`. Two more,
`README.md` and `src/<package>/__init__.py`, are written only into a project that does not
have them, and `uv init --package` writes both, so on the path above they are kept instead.
The README a scaffolded project reads is therefore the one `uv` wrote, and the one this
command carries reaches only a project that had none.

**A file already there is kept rather than overwritten**, so running this again destroys no
work: a second run reports the whole scaffold as kept and changes nothing. `--force`
replaces a file that would have been kept.

### What it edits in the manifest

Three entries, each added only where the manifest does not already declare it, and each
reported by name in the output:

- **The transport.** `bustan[starlette]` under `[project]` dependencies, because the entry
  point serves on the adapter this package ships and installing `bustan` installs no web
  server. A manifest already naming `bustan` without an extra has the extra added to that
  entry and keeps whatever bound it carries; one that already asks for an extra is left
  exactly as it stands.
- **The scripts.** `start` and `dev` under `[project.scripts]`, both naming the entry point
  module rather than the package, so a package whose `__init__.py` came from somewhere else
  keeps whatever `main` it already meant.
- **The tools.** `pytest`, `ruff` and `ty` in the `dev` dependency group.

The manifest is decided from its parsed tables and parsed again before it is written, so an
edit that would not land exactly as intended is refused rather than written. A manifest this
command cannot edit without changing what the rest of the file means is left alone, and the
refusal names the entries to add by hand.

### What it prints

Every path written, every path kept, every manifest edit, and what to run next:

```
Initialised Bustan app for package 'my_service'.
Wrote:
  src/my_service/app_main.py
  src/my_service/app_module.py
  src/my_service/app_controller.py
  src/my_service/app_service.py
  tests/my_service/test_app_controller.py
  tests/my_service/test_app_service.py
  tests/my_service/test_app_module.py
Kept:
  README.md
  src/my_service/__init__.py
Pass --force to replace a file that was kept.
Manifest: declared bustan[starlette]>=2.0.0 under [project] dependencies.
Manifest: added the 'start' and 'dev' script entries under [project.scripts].
Manifest: added pytest, ruff, ty to the 'dev' dependency group.
Next steps:
  uv sync
  uv run start
  uv run dev
```

The bound on the transport requirement is the version of the `bustan` that ran, so a run
prints whatever is installed rather than the figure above.

One `uv sync` is the whole install. The manifest now declares what a scaffolded project
needs in order to serve, test, lint and type-check, so there is no dependency to add by
hand afterwards, and the three lines under `Next steps` are the only commands to run.

## `bustan routes`

```
usage: bustan routes [-h] {snapshot,diff} ...
```

`bustan routes snapshot <target> [--output FILE]` compiles the application and writes a
deterministic JSON snapshot of its routes, to standard output or to a file. Commit the
file and the next snapshot can be compared against it.

`bustan routes diff <previous> <current>` compares two snapshot files and prints the
routes added, removed and changed, with the fields that changed named.

## `bustan governance`

```
usage: bustan governance [-h] {ownership,diff,conformance} ...
```

Three reports, each printed as JSON:

- `ownership <target>` - every route with the owner and deprecation metadata declared on
  it.
- `diff <target> --snapshot FILE` - the route diff against a snapshot, with a count of
  what was added, removed and changed.
- `conformance <adapter>` - the conformance result for one adapter, and the capabilities
  it declares. `starlette` and `asgi` are the two names it answers for, and any other name
  is refused as unsupported.

### `conformance starlette` needs `httpx`

The suite drives an adapter through the test client its own users would drive, and
Starlette's is driven by `httpx`, which the `starlette` extra does not install: a
deployment would carry it to run one diagnostic and never call it again. The report is
therefore a development-time check, and `httpx` is asked for as a development dependency:

```bash
uv add --dev httpx
```

Without it the command writes nothing to standard output and exits `1`, naming the same
install line:

```
A Starlette test client requires the optional 'httpx' dependency, which the starlette extra does not install.

Install it with:

    uv add --dev httpx
```

`conformance asgi` needs nothing beyond the package, because the raw ASGI adapter drives a
client of its own.

## The `--format` Option

`doctor`, `graph` and `config` take `--format table` (the default) or `--format json`.
The table is for a person and the JSON is for a script; both are rendered from the same
report, so the two cannot come to disagree about what a command found. Under
`--format json` the command writes one JSON object and nothing else to standard output.

`routes` and `governance` print JSON always, as they did before the option existed.
