# Multi-Module App Example

This example shows how exported providers from sibling feature modules are consumed by a root controller.

## Layout

```text
multi_module_app/
  README.md
  pyproject.toml
  src/
    multi_module_app/
      __init__.py
      app.py
      app_module.py
      auth_module.py
      auth_service.py
      user_controller.py
      users_module.py
      users_service.py
  tests/
    multi_module_app/
      test_app.py
```

## Run

```bash
cd examples/multi_module_app
uv sync --group dev
uv run python -m multi_module_app.app
```

## What It Demonstrates

- `UsersModule` exporting `UserService`
- `AuthModule` exporting `AuthService`
- a root controller consuming providers from both imported modules