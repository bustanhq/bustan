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
than from the new internal path. [STABILITY.md](STABILITY.md) says which those are.

The scan reports only what it can prove from the source. A change that leaves no trace
in the text of a program - a status code that moved, a shutdown that now drains, a body
field that is now checked against its declared type - is in
[CHANGELOG.md](../CHANGELOG.md) and cannot be found here.

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

```bash
uv init --package my-service
cd my-service
bustan init
```

Scaffolds an application into the current `uv` project: a module, a controller, a service,
their tests, a README, and the `start` and `dev` scripts. It reads the package name out of
`pyproject.toml`, so run it from the project root. The command prints the install steps to
follow it, and the scaffolded README repeats them.

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
  it declares.

## The `--format` Option

`doctor`, `graph` and `config` take `--format table` (the default) or `--format json`.
The table is for a person and the JSON is for a script; both are rendered from the same
report, so the two cannot come to disagree about what a command found. Under
`--format json` the command writes one JSON object and nothing else to standard output.

`routes` and `governance` print JSON always, as they did before the option existed.
