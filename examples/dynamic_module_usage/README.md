# Dynamic Module Example

This example shows a configurable dynamic module that registers providers from runtime input.

## Layout

```text
dynamic_module_usage/
  README.md
  pyproject.toml
  src/
    dynamic_module_usage/
      __init__.py
      app.py
      app_controller.py
      app_module.py
      cache_module.py
      cache_service.py
  tests/
    dynamic_module_usage/
      test_app.py
```

## Run

```bash
cd examples/dynamic_module_usage
uv sync --group dev
uv run python -m dynamic_module_usage.app
```

## What It Demonstrates

- registering a `DynamicModule` from runtime configuration
- injecting a typed `InjectionToken`
- using a factory provider to build a service from dynamic input