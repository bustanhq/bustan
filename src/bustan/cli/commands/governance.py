"""Governance reporting and release-gate command handlers."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Callable, cast

from ...app.bootstrap import create_app
from ...platform.http.conformance import evaluate_adapter_conformance, load_adapter
from ...platform.http.registry import diff_route_snapshots
from .routes import _load_root_module, _load_snapshot

if TYPE_CHECKING:
    from ...app.application import Application
    from ...platform.http.compiler import RouteContract


def register_governance_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser("governance", help="Render governance and release-gate reports.")
    governance_subparsers = parser.add_subparsers(dest="governance_command")

    ownership_parser = governance_subparsers.add_parser(
        "ownership",
        help="Render route ownership and deprecation metadata from compiled artifacts.",
    )
    ownership_parser.add_argument("target", help="Root module import path in the form package.module:RootModule")

    diff_parser = governance_subparsers.add_parser(
        "diff",
        help="Render a governance summary for a compiled route diff.",
    )
    diff_parser.add_argument("target", help="Root module import path in the form package.module:RootModule")
    diff_parser.add_argument("--snapshot", required=True, help="Path to the previous route snapshot JSON file.")

    conformance_parser = governance_subparsers.add_parser(
        "conformance",
        help="Render adapter conformance results.",
    )
    conformance_parser.add_argument("adapter", help="Adapter name to evaluate.")

    gate_parser = governance_subparsers.add_parser(
        "release-gate",
        help="Evaluate route diff and adapter conformance release gates.",
    )
    gate_parser.add_argument("target", help="Root module import path in the form package.module:RootModule")
    gate_parser.add_argument("--snapshot", required=True, help="Path to the previous route snapshot JSON file.")
    gate_parser.add_argument(
        "--config",
        default="release/config.json",
        help="Path to the release-gate policy config JSON file.",
    )
    gate_parser.add_argument(
        "--manifest",
        default="release/manifest.json",
        help="Path to the release-gate manifest JSON file.",
    )


def run_governance_command(arguments: argparse.Namespace) -> int:
    command = getattr(arguments, "governance_command", None)
    if command == "ownership":
        return _run_json_command(_build_ownership_report, arguments.target)
    if command == "diff":
        return _run_json_command(_build_diff_report, arguments.target, arguments.snapshot)
    if command == "conformance":
        return _run_json_command(_build_conformance_report, arguments.adapter)
    if command == "release-gate":
        return _run_release_gate(arguments)

    print("A governance subcommand is required.", file=sys.stderr)
    return 1


def _run_json_command(builder: Callable[..., dict[str, object]], *args: str) -> int:
    try:
        payload = builder(*args)
    except (AttributeError, ImportError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _run_release_gate(arguments: argparse.Namespace) -> int:
    try:
        payload = _build_release_gate_report(
            arguments.target,
            arguments.snapshot,
            arguments.config,
            arguments.manifest,
        )
    except (AttributeError, ImportError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["passed"] else 1


def _build_ownership_report(target: str) -> dict[str, object]:
    application = _create_compiled_app(target)
    routes: list[dict[str, object]] = []
    for contract in _sorted_route_contracts(application.route_contracts):
        deprecation = contract.policy_plan.deprecation
        routes.append(
            {
                "module": _display_route_module(contract),
                "controller": contract.controller_cls.__name__,
                "handler": contract.handler_name,
                "method": contract.method,
                "path": contract.path,
                "owner": contract.policy_plan.owner,
                "deprecation": {
                    "since": deprecation.since,
                    "sunset": deprecation.sunset,
                    "replacement": deprecation.replacement,
                }
                if deprecation is not None
                else None,
            }
        )
    return {"routes": tuple(routes)}


def _build_diff_report(target: str, snapshot_path: str) -> dict[str, object]:
    application = _create_compiled_app(target)
    previous_snapshot = _load_snapshot(Path(snapshot_path))
    diff = diff_route_snapshots(previous_snapshot, application.snapshot_routes())
    summary = Counter(entry["change"] for entry in diff)
    return {
        "summary": {
            "added": summary.get("added", 0),
            "removed": summary.get("removed", 0),
            "changed": summary.get("changed", 0),
        },
        "diff": diff,
    }


def _build_conformance_report(adapter_name: str) -> dict[str, object]:
    return evaluate_adapter_conformance(load_adapter(adapter_name)).to_dict()


def _build_release_gate_report(
    target: str,
    snapshot_path: str,
    config_path: str,
    manifest_path: str,
) -> dict[str, object]:
    diff_report = _build_diff_report(target, snapshot_path)
    summary = cast(dict[str, int], diff_report["summary"])
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    policy = config.get("bustan-governance", {}).get("release-gate", {})
    expected_conformance = manifest.get("bustan-governance", {}).get("adapter-conformance", {})

    errors: list[str] = []
    if summary["removed"] > policy.get("max_removed_routes", 0):
        errors.append("removed routes exceed the configured release gate")
    if summary["changed"] > policy.get("max_changed_routes", 0):
        errors.append("changed routes exceed the configured release gate")

    conformance_reports: dict[str, dict[str, object]] = {}
    if policy.get("require_adapter_conformance", False):
        for adapter_name in policy.get("adapters", []):
            report = _build_conformance_report(adapter_name)
            conformance_reports[adapter_name] = report
            if not report["passed"]:
                errors.append(f"adapter {adapter_name} failed conformance")
            expected_capabilities = expected_conformance.get(adapter_name)
            if expected_capabilities is not None and report["capabilities"] != expected_capabilities:
                errors.append(f"adapter {adapter_name} capabilities drifted from the release manifest")

    return {
        "passed": not errors,
        "errors": tuple(errors),
        "diff": diff_report,
        "conformance": conformance_reports,
    }


def _create_compiled_app(target: str) -> Application:
    return create_app(_load_root_module(target), _no_lifespan=True)


def _sorted_route_contracts(
    route_contracts: tuple[RouteContract, ...],
) -> tuple[RouteContract, ...]:
    return tuple(
        sorted(
            route_contracts,
            key=lambda contract: (
                contract.method,
                contract.path,
                contract.versions,
                contract.controller_cls.__qualname__,
                contract.handler_name,
            ),
        )
    )


def _display_route_module(contract: object) -> str:
    module_key = getattr(contract, "module_key")
    if isinstance(module_key, type):
        return module_key.__name__
    module = getattr(module_key, "module", None)
    if isinstance(module, type):
        return module.__name__
    return repr(module_key)