#!/usr/bin/env python3
"""Smoke test to ensure the README quickstart is executable."""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
README_PATH = REPO_ROOT / "README.md"


def main() -> int:
    if not README_PATH.exists():
        print(f"Error: {README_PATH} not found")
        return 1

    content = README_PATH.read_text(encoding="utf-8")

    # Find the Five-Minute Quickstart section
    match = re.search(
        r"## Five-Minute Quickstart.*?```python\n(.*?)```", content, re.DOTALL | re.IGNORECASE
    )
    if not match:
        print("Error: Could not find quickstart code block in README.md")
        return 1

    code = match.group(1)
    
    print("--- README Quickstart Code ---")
    print(code)
    print("------------------------------")

    # We need to make sure 'bustan' is in the path
    sys.path.insert(0, str(REPO_ROOT / "src"))

    # Execute the code in a local namespace
    namespace = {}
    try:
        exec(code, namespace)
    except Exception as e:
        print(f"Error executing README quickstart: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Verify 'app' exists and is the right type
    if "app" not in namespace:
        print("Error: 'app' variable not found in quickstart namespace")
        return 1

    from bustan import Application
    app = namespace["app"]
    if not isinstance(app, Application):
        print(f"Error: 'app' is not an instance of Application (got {type(app)})")
        return 1

    print("SUCCESS: README quickstart is executable and valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
