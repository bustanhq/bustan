# Testing Overrides Example

This example shows the two supported testing override patterns: create-time overrides with `create_test_app()` and assembled overrides with `create_testing_module()`.

Both register the replacement before the application starts, which is the only point at which an override is honoured in full: an override replaces a provider for the whole application, including every instance already built from it, so a running application refuses one rather than swapping a dependency that everything already holding it would keep.

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
- replacing providers in an application a test assembles and starts for itself
- serving requests against the replacement through the compiled module's own client
- keeping override behavior inside `bustan.testing`