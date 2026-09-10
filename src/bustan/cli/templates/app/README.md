# $project_name

A [Bustan](https://github.com/bustanhq/bustan) application.

## Getting started

`bustan init` declared everything this project needs in `pyproject.toml`, so one
command installs it:

```sh
uv sync
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

Under `uv run dev` the server watches `src/` and restarts on every change, so editing a
handler changes the next response without stopping anything.

## Project structure

```
src/
  $package_name/
    app_main.py          # app entry point (bootstrap, main, dev)
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
