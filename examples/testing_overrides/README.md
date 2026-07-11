# Testing Overrides Example

This example shows the two supported testing override patterns: create-time overrides with `create_test_app()` and scoped overrides with `override_provider()`.

## Layout

```text
testing_overrides/
  README.md
  pyproject.toml
  src/
    testing_overrides/
      __init__.py
      app.py
      app_module.py
      fake_greeting_service.py
      greeting_controller.py
      greeting_service.py
  tests/
    testing_overrides/
      test_app.py
```

## Run

```bash
cd examples/testing_overrides
uv sync --group dev
uv run python -m testing_overrides.app
```

## What It Demonstrates

- replacing providers while building a test application
- temporarily overriding providers on an existing test application
- keeping override behavior inside `bustan.testing`