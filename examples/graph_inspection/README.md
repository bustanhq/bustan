# Graph Inspection Example

This example shows supported runtime inspection through `DiscoveryModule`, `DiscoveryService`, and `Application.snapshot_routes()`.

## Layout

```text
graph_inspection/
  README.md
  pyproject.toml
  src/
    graph_inspection/
      __init__.py
      app.py
      app_module.py
      catalog_controller.py
      catalog_module.py
      catalog_service.py
  tests/
    graph_inspection/
      test_app.py
```

## Run

```bash
cd examples/graph_inspection
uv sync --group dev
uv run python -m graph_inspection.app
```

## What It Demonstrates

- runtime module and route discovery through `DiscoveryService`
- deterministic route snapshots through `Application.snapshot_routes()`
- supported inspection without reading private container internals