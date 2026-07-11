# $project_name

A [Bustan](https://github.com/bustanhq/bustan) application.

## Getting started

Install dependencies:

```sh
uv sync
```

Add Bustan and dev tools if not already present:

```sh
uv add bustan
uv add --dev ty ruff pytest
```

## Running the app

Start without reload:

```sh
uv run start
```

Start with hot-reload (development mode):

```sh
uv run dev
```

The server listens on **http://localhost:3000** by default.

## Project structure

```
src/
  $package_name/
    __init__.py          # app entry point (bootstrap, main, dev)
    app_module.py        # root module
    app_controller.py    # root controller
    app_service.py       # root service
tests/
  $package_name/
    test_app_controller.py
    test_app_service.py
    test_app_module.py
```

## Running tests

```sh
uv run pytest
```

## Linting and type-checking

```sh
uv run ruff check .
uv run ty check src tests
```
