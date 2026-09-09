# Containerise An Application

How to build a Bustan application into a container image and wire its probes to an orchestrator.

This is a starting point rather than a specification. Base images, registries and orchestrators
change faster than anything else here, so treat the Dockerfile as a shape to adapt, and check the
versions against what your platform actually offers.

For what happens once the container is running - draining, workers, proxies - see
[Deploy An Application](deploy.md). This page only gets it built and scheduled.

## The Dockerfile

Two stages. The first resolves dependencies with uv; the second carries only the interpreter, the
virtual environment and your source.

```dockerfile
FROM python:3.13-slim AS build

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app

# Dependencies first, so a source change does not re-resolve them.
COPY pyproject.toml uv.lock ./
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

Three things there are deliberate.

**`uv sync --frozen` and nothing else.** `--frozen` fails rather than silently re-resolving, so the
image gets the dependencies the lockfile names and a stale lockfile is a build failure instead of a
surprise in production. uv is the only supported package manager; see
[the project README](../../README.md#install).

**Dependencies are copied and installed before the source.** A change to your code then reuses the
dependency layer, which is most of the image.

**`--no-dev` in both stages.** Test and lint tools have no business in a running image.

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
[Configuration End To End](../tutorials/configuration-end-to-end.md) set up.

## Build And Run It

```bash
docker build -t my-app:local .
docker run --rm -p 3000:3000 \
  -e DATABASE_PATH=/data/tasks.db \
  -e API_TOKEN=... \
  my-app:local
```

Check the probes answer before going further:

```bash
curl -fsS http://127.0.0.1:3000/health/live
curl -fsS http://127.0.0.1:3000/health/ready
```

## Wire The Probes

The two probes answer different questions and must be wired to different things. Liveness asks
whether the process is worth keeping; readiness asks whether it should be sent traffic. Wiring
readiness to the liveness slot causes restart loops under load, and the reasoning is in
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

TLS, ingress, secrets management, image scanning and registry policy are all platform decisions with
no Bustan-specific answer. The application reads configuration from the environment and answers two
probes; everything else is your platform's business.

Databases in particular: the example uses sqlite so it needs no service, and a real deployment
points `DATABASE_PATH` or its equivalent at a managed one. Whatever you connect to, open it in
`on_application_bootstrap` and dispose it in `on_module_destroy` as
[A Datastore And A Readiness Probe](../tutorials/a-datastore-and-a-readiness-probe.md) shows, so a
restart does not leak connections.
