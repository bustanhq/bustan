# Examples

Each example now mirrors the standalone mini-project layout under `.bustan/mini`:

- `README.md`
- `pyproject.toml`
- `src/<package>/...`
- `tests/<package>/...`

That keeps the checked-in examples aligned with the scaffold story, not just with the generated package internals.

## Run An Example

Each example is its own small `uv` project wired back to the repository root through a local editable `bustan` source.

```bash
cd examples/blog_api
uv sync --group dev
uv run python -m blog_api.app
```

Replace `blog_api` with any of the example directories below.

## Example Index

- `examples/blog_api`: reference-style blog API with feature modules, exports, and request-scoped actor state
- `examples/multi_module_app`: exported providers crossing feature-module boundaries
- `examples/graph_inspection`: supported runtime inspection using `DiscoveryService` and route snapshots
- `examples/request_scope_pipeline_app`: one request-scoped provider shared across guard, interceptor, and request-scoped controller
- `examples/testing_overrides`: `create_test_app()` and `override_provider()` in action
- `examples/dynamic_module_usage`: a configurable dynamic module that registers providers from runtime input