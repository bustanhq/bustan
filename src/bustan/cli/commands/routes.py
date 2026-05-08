"""Route snapshot and diff command handlers."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import cast

from ...app.bootstrap import _create_app
from ...platform.http.registry import diff_route_snapshots


def register_routes_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("routes", help="Inspect compiled application routes.")
    route_subparsers = parser.add_subparsers(dest="routes_command")

    snapshot_parser = route_subparsers.add_parser(
        "snapshot",
        help="Create a deterministic route snapshot from a root module.",
    )
    snapshot_parser.add_argument(
        "target",
        help="Root module import path in the form package.module:RootModule",
    )
    snapshot_parser.add_argument(
        "--output",
        help="Write the route snapshot to this file instead of stdout.",
    )

    diff_parser = route_subparsers.add_parser(
        "diff",
        help="Compare two previously-generated route snapshots.",
    )
    diff_parser.add_argument("previous", help="Path to the previous snapshot JSON file.")
    diff_parser.add_argument("current", help="Path to the current snapshot JSON file.")


def run_routes_command(arguments: argparse.Namespace) -> int:
    command = getattr(arguments, "routes_command", None)
    if command == "snapshot":
        return run_snapshot_command(arguments)
    if command == "diff":
        return run_diff_command(arguments)

    print("A routes subcommand is required.", file=sys.stderr)
    return 1


def run_snapshot_command(arguments: argparse.Namespace) -> int:
    try:
        root_module = _load_root_module(arguments.target)
        snapshot = _create_app(root_module, no_lifespan=True).snapshot_routes()
        rendered = json.dumps(snapshot, indent=2, sort_keys=True)
        output = getattr(arguments, "output", None)
        if output:
            Path(output).write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
    except (AttributeError, ImportError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0


def run_diff_command(arguments: argparse.Namespace) -> int:
    try:
        previous = _load_snapshot(Path(arguments.previous))
        current = _load_snapshot(Path(arguments.current))
        diff = diff_route_snapshots(previous, current)
        print(json.dumps(diff, indent=2, sort_keys=True))
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0


def _load_root_module(target: str) -> type[object]:
    module_name, separator, attribute_name = target.partition(":")
    if separator != ":" or not module_name or not attribute_name:
        raise ValueError("Route snapshot target must use the form package.module:RootModule")

    module = importlib.import_module(module_name)
    root_module = getattr(module, attribute_name)
    if not isinstance(root_module, type):
        raise ValueError(f"{target} did not resolve to a module class")
    return cast(type[object], root_module)


def _load_snapshot(path: Path) -> tuple[dict[str, object], ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Route snapshot {path} must contain a JSON array")

    entries: list[dict[str, object]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            raise ValueError(f"Route snapshot {path} contains a non-object entry")
        entries.append(dict(entry))
    return tuple(entries)