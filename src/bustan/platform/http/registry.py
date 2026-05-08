"""Compiled route validation and snapshot helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from ...core.errors import RouteDefinitionError
from ...core.utils import _display_name, _qualname
from .compiler import RouteContract
from .versioning import VERSION_NEUTRAL

RouteSnapshot = tuple[dict[str, object], ...]
RouteSnapshotDiff = tuple[dict[str, object], ...]
_SNAPSHOT_DIMENSIONS = ("module", "name", "method", "path", "versions", "hosts")


class RouteRegistry:
    """Consume compiled route contracts for diagnostics and snapshots."""

    def __init__(self, contracts: tuple[RouteContract, ...]) -> None:
        self._contracts = contracts

    def validate(self) -> None:
        seen_exact: dict[tuple[str, str, tuple[str, ...], tuple[str, ...]], RouteContract] = {}
        seen_patterns: list[RouteContract] = []

        for contract in self._contracts:
            exact_key = (contract.method, contract.path, contract.versions, contract.hosts)
            previous_exact = seen_exact.get(exact_key)
            if previous_exact is not None:
                raise RouteDefinitionError(
                    f"Duplicate application route {contract.method} {contract.path} declared by "
                    f"{_describe_contract(previous_exact)} and {_describe_contract(contract)}"
                )

            for previous_contract in seen_patterns:
                if not _route_dimensions_overlap(previous_contract, contract):
                    continue
                if _canonical_path_pattern(previous_contract.path) == _canonical_path_pattern(contract.path):
                    raise RouteDefinitionError(
                        f"Conflicting route path pattern for {contract.method} "
                        f"{_canonical_path_pattern(contract.path)} declared by "
                        f"{_describe_contract(previous_contract)} and {_describe_contract(contract)}"
                    )

            seen_exact[exact_key] = contract
            seen_patterns.append(contract)

    def snapshot(self) -> RouteSnapshot:
        return snapshot_route_contracts(self._contracts)


def snapshot_route_contracts(contracts: tuple[RouteContract, ...]) -> RouteSnapshot:
    ordered_contracts = sorted(
        contracts,
        key=lambda contract: (
            contract.method,
            contract.path,
            contract.versions,
            contract.controller_cls.__qualname__,
            contract.handler_name,
        ),
    )
    return tuple(
        {
            "module": _display_name(contract.module_key),
            "controller": contract.controller_cls.__name__,
            "handler": contract.handler_name,
            "name": contract.name,
            "method": contract.method,
            "path": contract.path,
            "versions": list(contract.versions),
            "hosts": list(contract.hosts),
        }
        for contract in ordered_contracts
    )


def diff_route_snapshots(
    previous: Sequence[Mapping[str, object]],
    current: Sequence[Mapping[str, object]],
) -> RouteSnapshotDiff:
    previous_by_identity = {
        _snapshot_identity(entry): _normalize_snapshot_entry(entry) for entry in previous
    }
    current_by_identity = {
        _snapshot_identity(entry): _normalize_snapshot_entry(entry) for entry in current
    }

    diff: list[dict[str, object]] = []
    for identity in sorted(set(previous_by_identity) | set(current_by_identity)):
        before = previous_by_identity.get(identity)
        after = current_by_identity.get(identity)
        route = f"{identity[0]}.{identity[1]}"
        if before is None:
            diff.append(
                {
                    "change": "added",
                    "route": route,
                    "before": None,
                    "after": after,
                    "fields": [],
                }
            )
            continue
        if after is None:
            diff.append(
                {
                    "change": "removed",
                    "route": route,
                    "before": before,
                    "after": None,
                    "fields": [],
                }
            )
            continue

        changed_fields = [
            field for field in _SNAPSHOT_DIMENSIONS if before[field] != after[field]
        ]
        if changed_fields:
            diff.append(
                {
                    "change": "changed",
                    "route": route,
                    "before": before,
                    "after": after,
                    "fields": changed_fields,
                }
            )

    return tuple(diff)


def _describe_contract(contract: RouteContract) -> str:
    return f"{_qualname(contract.controller_cls)}.{contract.handler_name} in {_display_name(contract.module_key)}"


def _route_dimensions_overlap(left: RouteContract, right: RouteContract) -> bool:
    return (
        left.method == right.method
        and left.hosts == right.hosts
        and _versions_overlap(left.versions, right.versions)
    )


def _versions_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    left_neutral = not left or VERSION_NEUTRAL in left
    right_neutral = not right or VERSION_NEUTRAL in right
    if left_neutral and right_neutral:
        return True
    if left_neutral or right_neutral:
        return False
    return bool(set(left) & set(right))


def _canonical_path_pattern(path: str) -> str:
    if path == "/":
        return path

    normalized_segments: list[str] = []
    for segment in path.strip("/").split("/"):
        if segment.startswith("{*") and segment.endswith("}"):
            normalized_segments.append("*")
            continue
        if segment.startswith("{") and segment.endswith("}"):
            normalized_segments.append("{}")
            continue
        if "*" in segment:
            normalized_segments.append(segment.replace(segment, "*"))
            continue
        normalized_segments.append(segment)

    return "/" + "/".join(normalized_segments)


def _snapshot_identity(entry: Mapping[str, object]) -> tuple[str, str]:
    return (
        str(entry["controller"]),
        str(entry["handler"]),
    )


def _normalize_snapshot_entry(entry: Mapping[str, object]) -> dict[str, object]:
    return {
        "module": str(entry["module"]),
        "controller": str(entry["controller"]),
        "handler": str(entry["handler"]),
        "name": str(entry["name"]),
        "method": str(entry["method"]),
        "path": str(entry["path"]),
        "versions": [str(version) for version in cast(Sequence[object], entry["versions"])],
        "hosts": [str(host) for host in cast(Sequence[object], entry["hosts"])],
    }