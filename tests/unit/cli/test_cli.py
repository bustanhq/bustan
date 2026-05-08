"""Unit tests for the Bustan CLI init command."""

import argparse
import json
import os
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

import bustan.cli.main as cli_main_module
from bustan.cli.commands import governance as governance_commands
from bustan.cli.commands import routes as routes_commands
from bustan.cli.main import main

_PYPROJECT_TOML = """\
[project]
name = "{name}"
version = "0.1.0"
description = "Test project"
requires-python = ">=3.13"
dependencies = []

[build-system]
requires = ["uv_build>=0.11.6,<0.12.0"]
build-backend = "uv_build"
"""


def _write_pyproject(directory: Path, name: str) -> None:
    (directory / "pyproject.toml").write_text(
        _PYPROJECT_TOML.format(name=name), encoding="utf-8"
    )


def test_init_creates_expected_files(tmp_path: Path, capsys) -> None:
    _write_pyproject(tmp_path, "hello-bustan")
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        exit_code = main(["init"])
    finally:
        os.chdir(old_cwd)

    assert exit_code == 0
    assert (tmp_path / "README.md").exists()
    pkg = tmp_path / "src" / "hello_bustan"
    assert (pkg / "__init__.py").exists()
    assert (pkg / "app_module.py").exists()
    assert (pkg / "app_controller.py").exists()
    assert (pkg / "app_service.py").exists()
    tests = tmp_path / "tests" / "hello_bustan"
    assert (tests / "test_app_controller.py").exists()
    assert (tests / "test_app_service.py").exists()
    assert (tests / "test_app_module.py").exists()
    stdout = capsys.readouterr().out
    assert "hello_bustan" in stdout
    assert "uv add --dev ty ruff pytest" in stdout
    assert "uv run start" in stdout
    assert "uv run dev" in stdout


def test_init_adds_scripts_to_pyproject(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, "my-app")
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        main(["init"])
    finally:
        os.chdir(old_cwd)

    content = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert '[project.scripts]' in content
    assert 'start = "my_app:main"' in content
    assert 'dev = "my_app:dev"' in content


def test_init_fails_without_pyproject(tmp_path: Path, capsys) -> None:
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        exit_code = main(["init"])
    finally:
        os.chdir(old_cwd)

    assert exit_code == 1
    assert "pyproject.toml" in capsys.readouterr().err


def test_init_init_py_contains_bootstrap_and_scripts(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, "demo-app")
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        main(["init"])
    finally:
        os.chdir(old_cwd)

    content = (tmp_path / "src" / "demo_app" / "__init__.py").read_text(encoding="utf-8")
    assert "def bootstrap" in content
    assert "def main" in content
    assert "def dev" in content


def test_main_prints_help_when_no_command_is_supplied(capsys) -> None:
    assert main([]) == 1
    assert "usage:" in capsys.readouterr().out


def test_main_uses_parser_error_for_unsupported_commands(monkeypatch) -> None:
    class ParserStub:
        def __init__(self) -> None:
            self.error_message: str | None = None

        def parse_args(self, argv):
            return argparse.Namespace(command="unsupported")

        def print_help(self) -> None:
            return None

        def error(self, message: str) -> None:
            self.error_message = message

    parser = ParserStub()
    monkeypatch.setattr(cli_main_module, "_build_parser", lambda: parser)

    assert cli_main_module.main(["unsupported"]) == 2
    assert parser.error_message == "Unsupported command: unsupported"


def test_routes_snapshot_writes_deterministic_route_snapshot(tmp_path: Path) -> None:
    route_module = tmp_path / "sample_app.py"
    route_module.write_text(
        """
from bustan import Controller, Get, Module


@Controller(\"/zeta\")
class ZetaController:
    @Get(\"/\")
    def index(self) -> dict[str, str]:
        return {\"controller\": \"zeta\"}


@Controller(\"/alpha\")
class AlphaController:
    @Get(\"/\")
    def index(self) -> dict[str, str]:
        return {\"controller\": \"alpha\"}


@Module(controllers=[ZetaController, AlphaController])
class AppModule:
    pass
""".strip()
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "routes.json"
    old_cwd = os.getcwd()
    old_sys_path = list(sys.path)
    sys.path.insert(0, str(tmp_path))
    os.chdir(tmp_path)
    try:
        exit_code = main(["routes", "snapshot", "sample_app:AppModule", "--output", str(output)])
    finally:
        os.chdir(old_cwd)
        sys.path[:] = old_sys_path

    assert exit_code == 0
    snapshot = json.loads(output.read_text(encoding="utf-8"))
    assert [item["path"] for item in snapshot] == ["/alpha", "/zeta"]


def test_routes_diff_reports_added_removed_and_changed_routes(tmp_path: Path, capsys) -> None:
    previous = tmp_path / "previous.json"
    current = tmp_path / "current.json"
    previous.write_text(
        json.dumps(
            [
                {
                    "module": "tests.AppModule",
                    "controller": "AlphaController",
                    "handler": "index",
                    "name": "index",
                    "method": "GET",
                    "path": "/alpha",
                    "versions": [],
                    "hosts": [],
                },
                {
                    "module": "tests.AppModule",
                    "controller": "UsersController",
                    "handler": "index",
                    "name": "index",
                    "method": "GET",
                    "path": "/users",
                    "versions": [],
                    "hosts": [],
                },
            ]
        ),
        encoding="utf-8",
    )
    current.write_text(
        json.dumps(
            [
                {
                    "module": "tests.AppModule",
                    "controller": "BetaController",
                    "handler": "index",
                    "name": "index",
                    "method": "GET",
                    "path": "/beta",
                    "versions": [],
                    "hosts": [],
                },
                {
                    "module": "tests.AppModule",
                    "controller": "UsersController",
                    "handler": "index",
                    "name": "index",
                    "method": "GET",
                    "path": "/members",
                    "versions": [],
                    "hosts": [],
                },
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(["routes", "diff", str(previous), str(current)])

    assert exit_code == 0
    diff = json.loads(capsys.readouterr().out)
    assert [entry["change"] for entry in diff] == ["removed", "added", "changed"]
    assert diff[2]["fields"] == ["path"]


def test_governance_ownership_reports_owner_and_deprecation_metadata(tmp_path: Path, capsys) -> None:
    route_module = tmp_path / "governance_app.py"
    route_module.write_text(
        """
from bustan import Controller, Get, Module
from bustan.security import DeprecatedRoute, Owner


@Owner(\"identity-platform\")
@Controller(\"/users\")
class UsersController:
    @DeprecatedRoute(sunset=\"2026-12-31\", replacement=\"/v2/users\")
    @Get(\"/\")
    def index(self) -> dict[str, str]:
        return {\"status\": \"ok\"}


@Module(controllers=[UsersController])
class AppModule:
    pass
""".strip()
        + "\n",
        encoding="utf-8",
    )
    old_cwd = os.getcwd()
    old_sys_path = list(sys.path)
    sys.path.insert(0, str(tmp_path))
    os.chdir(tmp_path)
    try:
        exit_code = main(["governance", "ownership", "governance_app:AppModule"])
    finally:
        os.chdir(old_cwd)
        sys.path[:] = old_sys_path

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["routes"][0]["owner"] == "identity-platform"
    assert report["routes"][0]["deprecation"] == {
        "since": None,
        "sunset": "2026-12-31",
        "replacement": "/v2/users",
    }


def test_governance_diff_reports_summary_from_compiled_artifacts(tmp_path: Path, capsys) -> None:
    route_module = tmp_path / "governance_diff_app.py"
    route_module.write_text(
        """
from bustan import Controller, Get, Module


@Controller(\"/members\")
class UsersController:
    @Get(\"/\")
    def index(self) -> dict[str, str]:
        return {\"status\": \"ok\"}


@Module(controllers=[UsersController])
class AppModule:
    pass
""".strip()
        + "\n",
        encoding="utf-8",
    )
    previous = tmp_path / "previous-governance.json"
    previous.write_text(
        json.dumps(
            [
                {
                    "module": "AppModule",
                    "controller": "UsersController",
                    "handler": "index",
                    "name": "index",
                    "method": "GET",
                    "path": "/users",
                    "versions": [],
                    "hosts": [],
                }
            ]
        ),
        encoding="utf-8",
    )
    old_cwd = os.getcwd()
    old_sys_path = list(sys.path)
    sys.path.insert(0, str(tmp_path))
    os.chdir(tmp_path)
    try:
        exit_code = main(
            [
                "governance",
                "diff",
                "governance_diff_app:AppModule",
                "--snapshot",
                str(previous),
            ]
        )
    finally:
        os.chdir(old_cwd)
        sys.path[:] = old_sys_path

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary"] == {"added": 0, "removed": 0, "changed": 1}
    assert report["diff"][0]["fields"] == ["path"]


def test_governance_conformance_reports_adapter_capabilities(capsys) -> None:
    exit_code = main(["governance", "conformance", "starlette"])

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["adapter"] == "starlette"
    assert report["passed"] is True
    assert report["capabilities"]["supports_raw_body"] is True


def test_governance_release_gate_fails_when_policy_is_exceeded(tmp_path: Path, capsys) -> None:
    route_module = tmp_path / "release_gate_app.py"
    route_module.write_text(
        """
from bustan import Controller, Get, Module


@Controller(\"/members\")
class UsersController:
    @Get(\"/\")
    def index(self) -> dict[str, str]:
        return {\"status\": \"ok\"}


@Module(controllers=[UsersController])
class AppModule:
    pass
""".strip()
        + "\n",
        encoding="utf-8",
    )
    previous = tmp_path / "previous-release-gate.json"
    previous.write_text(
        json.dumps(
            [
                {
                    "module": "AppModule",
                    "controller": "LegacyController",
                    "handler": "index",
                    "name": "index",
                    "method": "GET",
                    "path": "/legacy",
                    "versions": [],
                    "hosts": [],
                },
                {
                    "module": "AppModule",
                    "controller": "UsersController",
                    "handler": "index",
                    "name": "index",
                    "method": "GET",
                    "path": "/users",
                    "versions": [],
                    "hosts": [],
                },
            ]
        ),
        encoding="utf-8",
    )
    config = tmp_path / "release-config.json"
    config.write_text(
        json.dumps(
            {
                "bustan-governance": {
                    "release-gate": {
                        "max_removed_routes": 0,
                        "max_changed_routes": 0,
                        "adapters": ["starlette"],
                        "require_adapter_conformance": True,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "release-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "bustan-governance": {
                    "adapter-conformance": {
                        "starlette": {
                            "supports_host_routing": True,
                            "supports_raw_body": True,
                            "supports_streaming_responses": True,
                            "supports_websocket_upgrade": False,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    old_cwd = os.getcwd()
    old_sys_path = list(sys.path)
    sys.path.insert(0, str(tmp_path))
    os.chdir(tmp_path)
    try:
        exit_code = main(
            [
                "governance",
                "release-gate",
                "release_gate_app:AppModule",
                "--snapshot",
                str(previous),
                "--config",
                str(config),
                "--manifest",
                str(manifest),
            ]
        )
    finally:
        os.chdir(old_cwd)
        sys.path[:] = old_sys_path

    assert exit_code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["passed"] is False
    assert any("removed routes" in error for error in report["errors"])
    assert any("capabilities drifted" in error for error in report["errors"])


def test_routes_and_governance_commands_report_missing_subcommands(capsys) -> None:
    assert routes_commands.run_routes_command(argparse.Namespace(routes_command=None)) == 1
    assert governance_commands.run_governance_command(argparse.Namespace(governance_command=None)) == 1

    captured = capsys.readouterr()
    assert "routes subcommand" in captured.err
    assert "governance subcommand" in captured.err


def test_route_command_helpers_validate_targets_and_snapshots(tmp_path: Path) -> None:
    module_path = tmp_path / "not_a_module.py"
    module_path.write_text("VALUE = 1\n", encoding="utf-8")

    old_sys_path = list(sys.path)
    sys.path.insert(0, str(tmp_path))
    try:
        with pytest.raises(ValueError, match="form package.module:RootModule"):
            routes_commands._load_root_module("invalid")

        with pytest.raises(ValueError, match="did not resolve to a module class"):
            routes_commands._load_root_module("not_a_module:VALUE")
    finally:
        sys.path[:] = old_sys_path

    bad_snapshot = tmp_path / "bad.json"
    bad_snapshot.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON array"):
        routes_commands._load_snapshot(bad_snapshot)

    bad_entries = tmp_path / "bad-entries.json"
    bad_entries.write_text(json.dumps(["nope"]), encoding="utf-8")
    with pytest.raises(ValueError, match="non-object entry"):
        routes_commands._load_snapshot(bad_entries)


def test_route_and_governance_command_error_wrappers_return_failure(tmp_path: Path, capsys) -> None:
    assert routes_commands.run_snapshot_command(
        argparse.Namespace(target="broken", output=None)
    ) == 1

    invalid_snapshot = tmp_path / "invalid.json"
    invalid_snapshot.write_text("{", encoding="utf-8")
    assert routes_commands.run_diff_command(
        argparse.Namespace(previous=str(invalid_snapshot), current=str(invalid_snapshot))
    ) == 1

    assert governance_commands._run_json_command(
        lambda *args: (_ for _ in ()).throw(ValueError("boom"))
    ) == 1
    assert governance_commands._run_release_gate(
        argparse.Namespace(target="broken", snapshot="missing", config="missing", manifest="missing")
    ) == 1

    captured = capsys.readouterr()
    assert "boom" in captured.err


def test_governance_release_gate_can_pass_without_optional_conformance(tmp_path: Path, capsys) -> None:
    route_module = tmp_path / "passing_app.py"
    route_module.write_text(
        """
from bustan import Controller, Get, Module


@Controller(\"/users\")
class UsersController:
    @Get(\"/\")
    def index(self) -> dict[str, str]:
        return {\"status\": \"ok\"}


@Module(controllers=[UsersController])
class AppModule:
    pass
""".strip()
        + "\n",
        encoding="utf-8",
    )
    previous = tmp_path / "previous.json"
    previous.write_text(
        json.dumps(
            [
                {
                    "module": "AppModule",
                    "controller": "UsersController",
                    "handler": "index",
                    "name": "index",
                    "method": "GET",
                    "path": "/users",
                    "versions": [],
                    "hosts": [],
                }
            ]
        ),
        encoding="utf-8",
    )
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "bustan-governance": {
                    "release-gate": {
                        "max_removed_routes": 0,
                        "max_changed_routes": 0,
                        "require_adapter_conformance": False,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")

    old_cwd = os.getcwd()
    old_sys_path = list(sys.path)
    sys.path.insert(0, str(tmp_path))
    os.chdir(tmp_path)
    try:
        exit_code = main(
            [
                "governance",
                "release-gate",
                "passing_app:AppModule",
                "--snapshot",
                str(previous),
                "--config",
                str(config),
                "--manifest",
                str(manifest),
            ]
        )
    finally:
        os.chdir(old_cwd)
        sys.path[:] = old_sys_path

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["passed"] is True
    assert report["errors"] == []


def test_display_route_module_falls_back_to_repr_for_unknown_module_shape() -> None:
    contract = SimpleNamespace(module_key=SimpleNamespace(module="custom"))

    assert governance_commands._display_route_module(contract).startswith("namespace(")

