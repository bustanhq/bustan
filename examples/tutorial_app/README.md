# Tutorial app

The application the [Bustan tutorial series](../../docs/tutorials/) builds, at its end state.

Every tutorial in the series adds one layer to this project. Reading the finished code is not a
substitute for following the series, but it is the version that runs, and CI runs it: if a tutorial
and this directory disagree, this directory is right.

| Tutorial | What it added here |
| --- | --- |
| A resource with three routes | `tasks/`, the Pydantic payload, 201 on create and 404 on missing |
| Configuration end to end | `settings.py`, `.env`, `ConfigService` in the service |
| A datastore and a readiness probe | `task_store.py`, `store_indicator.py`, `tests/conftest.py` |
| Before the handler runs | `request_id_middleware.py`, `bearer_authenticator.py` |
| OpenAPI and Swagger UI | the document built in `__init__.py`, the `@Api*` decorators |

Run it:

```bash
uv sync --group dev
uv run python -m tutorial_app.app
uv run pytest
```

The store is `:memory:` here so CI writes nothing. A reader following the tutorials points
`DATABASE_PATH` at a file and their tasks survive a restart, which is the point tutorial 3 makes.
