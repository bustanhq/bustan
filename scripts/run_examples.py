#!/usr/bin/env python3

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

EXAMPLES: tuple[tuple[str, str], ...] = (
    ("examples/blog_api", "blog_api.app"),
    ("examples/multi_module_app", "multi_module_app.app"),
    ("examples/graph_inspection", "graph_inspection.app"),
    ("examples/request_scope_pipeline_app", "request_scope_pipeline_app.app"),
    ("examples/testing_overrides", "testing_overrides.app"),
    ("examples/dynamic_module_usage", "dynamic_module_usage.app"),
)


def main() -> int:
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)

    for relative_path, module_name in EXAMPLES:
        example_dir = ROOT / relative_path
        print(f"Running example {module_name} from {relative_path}")
        subprocess.run(
            ["uv", "run", "python", "-m", module_name],
            cwd=example_dir,
            check=True,
            env=env,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())