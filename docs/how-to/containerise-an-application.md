# Containerise An Application

How to build a Bustan application into a container image and wire its probes to an orchestrator.

Everything here was built and run before it was written down. Base images, registries and
orchestrators still change faster than documentation does, so check the versions against what your
platform offers, but the shape works.

For what happens once the container is running - draining, workers, proxies - see
[Deploy An Application](deploy.md). This page gets it built and reachable.

## First, Let The Application Bind Somewhere Else

This is the step that catches everyone, so it comes before the Dockerfile.

A scaffolded application listens on `127.0.0.1`, which is right on your laptop and useless in a
container: loopback inside the container is not reachable from outside it, whatever you publish with
`-p`. The container builds, starts, logs `Application startup complete`, and answers nothing.

Take the host from the environment. In `src/my_app/__init__.py`:

```python
import asyncio
import os

from bustan import create_app

from .app_module import AppModule


async def bootstrap(reload: bool = False) -> None:
    app = create_app(AppModule)
    await app.listen(
        port=int(os.environ.get("PORT", 3000)),
        host=os.environ.get("HOST", "127.0.0.1"),
        reload=reload,
    )
```

The default stays loopback, so nothing changes when you run it locally. The container sets
`HOST=0.0.0.0` and becomes reachable.

## The Dockerfile

Two stages. The first resolves dependencies with uv; the second carries only the interpreter, the
virtual environment and your source.

```dockerfile
FROM python:3.13-slim AS build

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app

# Dependencies first, so a source change does not re-resolve them. README.md is here
# because uv init writes `readme = "README.md"` into pyproject.toml, and building the
# project without it fails.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

COPY src ./src
RUN uv sync --frozen --no-dev


FROM python:3.13-slim

# A non-root user, because nothing here needs to be root.
RUN useradd --create-home --uid 10001 app
WORKDIR /app

COPY --from=build --chown=app:app /app/.venv /app/.venv
COPY --from=build --chown=app:app /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH"
USER app
EXPOSE 3000

CMD ["start"]
```

Four things there are deliberate.

**`README.md` is copied with the manifest.** Leaving it out is the first failure you will hit:
`failed to open file /app/README.md`, from the second `uv sync`, because that is where the project
itself gets built.

**`uv sync --frozen` and nothing else.** `--frozen` fails rather than silently re-resolving, so the
image gets the dependencies the lockfile names and a stale lockfile is a build failure instead of a
surprise in production. uv is the only supported package manager; see
[the project README](../../README.md#install).

**Dependencies are installed before the source is copied.** A change to your code then reuses the
dependency layer, which is most of the image.

**`--no-dev` in both stages.** Test and lint tools have no business in a running image. The result
is about 50 MB.

`CMD ["start"]` works because `bustan init` adds a `start` script to `pyproject.toml`, so
`/app/.venv/bin/start` exists. If you renamed it, or your project predates that, use the console
script your `[project.scripts]` actually defines.

## The `.dockerignore`

Without this the build context carries your virtual environment and your git history, and the image
may carry your `.env`.

```text
.venv/
.git/
.env
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
tests/
```

`.env` matters most. A local `.env` copied into an image is a credential in a layer, readable by
anyone who can pull it. Configuration reaches a container as environment variables, which is what
[Settings That Live Outside The Code](../tutorials/configuration-end-to-end.md) set up.

## Build And Run It

```bash
docker build -t my-app:local .
docker run --rm -p 3000:3000 -e HOST=0.0.0.0 my-app:local
```

```bash
curl http://127.0.0.1:3000/
```

```json
{"message":"Hello from My App"}
```

If that hangs or refuses instead, check the log. `Uvicorn running on http://127.0.0.1:3000` means
`HOST` did not reach the application; `http://0.0.0.0:3000` means it did.

## Wire The Probes

The probes exist once you have added the health module, which
[Links That Survive A Restart](../tutorials/a-datastore-and-a-readiness-probe.md) does. Without it
both paths answer `404`, and a `404` on a liveness probe reads as a dead container.

The two answer different questions and must be wired to different things. Liveness asks whether the
process is worth keeping; readiness asks whether it should be sent traffic. Wiring a database check
to liveness turns a brief database blip into a restart loop, and the reasoning is in
[the two probes](observe-an-application.md#the-two-probes-answer-different-questions).

```yaml
livenessProbe:
  httpGet:
    path: /health/live
    port: 3000
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /health/ready
    port: 3000
  periodSeconds: 5
```

**The grace period must exceed the drain timeout.** An application withdraws from readiness, lets
in-flight requests finish, then stops. If the orchestrator kills it first, it kills those requests.
Set `terminationGracePeriodSeconds` above the `drain_timeout` the application uses, with room to
spare; the sequence is in [shutdown and draining](deploy.md#shutdown-and-draining).

```yaml
terminationGracePeriodSeconds: 45
```

## What This Page Does Not Cover

TLS, ingress, secrets management, image scanning and registry policy are platform decisions with no
Bustan-specific answer. The application reads its configuration from the environment and answers two
probes; the rest is your platform's business.

Databases in particular. The tutorial uses sqlite so it needs no service, and a container writing to
a file in its own layer loses that file on every deploy. Point `DATABASE_PATH` at a mounted volume,
or at a managed database, and open it in `on_application_bootstrap` and dispose it in
`on_module_destroy` as the tutorial shows, so a restart does not leak connections.
