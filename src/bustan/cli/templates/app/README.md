# $project_name

This project was scaffolded with `bustan`.

## Quick start

```bash
uv sync --group dev
uv run uvicorn $package_name.app:app --reload
```

## Quality checks

```bash
uv run ruff check .
uv run ty check src tests
uv run pytest
```
