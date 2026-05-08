# Request Scope Pipeline Example

This example shows one request-scoped provider shared across a guard, an interceptor, and a request-scoped controller.

## Layout

```text
request_scope_pipeline_app/
  README.md
  pyproject.toml
  src/
    request_scope_pipeline_app/
      __init__.py
      account_controller.py
      app.py
      app_module.py
      authenticated_guard.py
      profile_service.py
      request_envelope_interceptor.py
      request_identity.py
  tests/
    request_scope_pipeline_app/
      test_app.py
```

## Run

```bash
cd examples/request_scope_pipeline_app
uv sync --group dev
uv run python -m request_scope_pipeline_app.app
```

## What It Demonstrates

- request-scoped provider caching per request
- request-scoped controller construction
- guard rejection before handler execution
- interceptor wrapping around the handler result