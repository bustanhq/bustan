# Blog API Example

This example shows a reference-style Bustan application with feature modules, exported providers, and request-scoped actor state.

## Layout

```text
blog_api/
  README.md
  pyproject.toml
  src/
    blog_api/
      __init__.py
      app.py
      app_module.py
      blog_controller.py
      blog_module.py
      blog_service.py
      identity_module.py
      models.py
      post_repository.py
      request_actor.py
  tests/
    blog_api/
      test_app.py
```

## Run

```bash
cd examples/blog_api
uv sync --group dev
uv run python -m blog_api.app
```

## What It Demonstrates

- feature-module composition through `BlogModule` and `IdentityModule`
- a request-scoped actor provider injected into a request-scoped controller
- exported singleton business services crossing module boundaries
- standard `bootstrap()`, `main()`, and `dev()` entry points under `src/blog_api/`