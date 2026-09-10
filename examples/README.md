# Examples

Each example is laid out the way `bustan init` scaffolds a project:

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

## Run An Example's Tests

Every example ships its own suite under `tests/<package>/`, and it is a real one: the
assertions there are what say the example still behaves the way its README claims.

```bash
cd examples/blog_api
uv run pytest
```

The root suite does not reach into `examples/`, so nothing else runs these. What runs
them everywhere - locally, in CI, in the release checklist - is
`scripts/run_examples.py`, from the repository root:

```bash
uv run python scripts/run_examples.py
```

It runs each example's application and then that example's suite, and prints the number
of tests each suite collected. An example whose suite collects nothing fails the run:
a suite that has quietly stopped being collected is otherwise indistinguishable from
one whose assertions all pass.

## Example Index

- `examples/blog_api`: reference-style blog API with feature modules, exports, and request-scoped actor state
- `examples/multi_module_app`: exported providers crossing feature-module boundaries
- `examples/graph_inspection`: supported runtime inspection using `DiscoveryService` and route snapshots
- `examples/request_scope_pipeline_app`: one request-scoped provider shared across guard, interceptor, and request-scoped controller
- `examples/testing_overrides`: `create_test_app()` and `override_provider()` in action
- `examples/dynamic_module_usage`: a configurable dynamic module that registers providers from runtime input
- `examples/link_shortener`: the link shortener the tutorial series builds, at its end state