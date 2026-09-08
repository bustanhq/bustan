"""Unit tests for the diagnostic half of the CLI: doctor, graph, config and --version.

Every test that needs an application writes one into ``tmp_path`` and imports it by a
name no other test uses, because an imported module stays in ``sys.modules`` for the
rest of the session and a shared name would hand one test another's application.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from pathlib import Path

import pytest

import bustan.cli.main as cli_main_module
from bustan.cli.commands import config as config_command
from bustan.cli.services import reporting
from bustan.cli.services.migrations import scan_path

_LEGACY_SOURCE = '''
"""An application written against the framework as 1.x shipped it."""

from bustan.core.ioc.tokens import InjectionToken
from bustan.logger.observability import MetricsSink
from bustan.config.config_service import ConfigService
from bustan.adapters.asgi import RequestBodyTooLarge

import bustan.platform.http.execution

from bustan import Controller, Get, RateLimit


class LegacyStorage:
    def increment(self, key: str, ttl: int) -> int:
        return 1

    def get_ttl(self, key: str) -> int:
        return 0


class LegacyMetrics:
    def record_request(self, *, labels) -> None:
        return None


class LegacySpan:
    def finish(self, *, status_code: int, error=None) -> None:
        return None


class LegacyTracer:
    def start_span(self, name: str, *, labels):
        return LegacySpan()


@Controller("/legacy")
class LegacyController:
    @RateLimit(limit=5, window="one minute")
    @Get("/")
    def index(self):
        return {}
'''

_MODERN_SOURCE = '''
"""An application already written against 2.0."""

from bustan import Controller, Get, Module, RateLimit


@Controller("/modern")
class ModernController:
    @RateLimit(limit=5, window="1m")
    @Get("/")
    def index(self) -> dict[str, str]:
        return {"status": "ok"}


@Module(controllers=[ModernController])
class AppModule:
    pass
'''

_APPLICATION_SOURCE = """
from bustan import Controller, Get, Injectable, Module
from bustan.configuration import ConfigModule


@Injectable()
class GreetingService:
    def greet(self) -> str:
        return "hello"


@Controller("/greetings")
class GreetingController:
    def __init__(self, greetings: GreetingService) -> None:
        self._greetings = greetings

    @Get("/")
    def index(self) -> dict[str, str]:
        return {"message": self._greetings.greet()}


@Module(
    imports=[ConfigModule.for_root(env_file="$env_file", is_global=True)],
    controllers=[GreetingController],
    providers=[GreetingService],
    exports=[GreetingService],
)
class AppModule:
    pass
"""

_BARE_APPLICATION_SOURCE = """
from bustan import Controller, Get, Module


@Controller("/bare")
class BareController:
    @Get("/")
    def index(self) -> dict[str, str]:
        return {"status": "ok"}


@Module(controllers=[BareController])
class AppModule:
    pass
"""

_UNRESOLVABLE_SOURCE = """
from bustan import Controller, Get, Injectable, Module


class Unregistered:
    pass


@Injectable()
class NeedsUnregistered:
    def __init__(self, missing: Unregistered) -> None:
        self._missing = missing


@Controller("/broken")
class BrokenController:
    def __init__(self, needs: NeedsUnregistered) -> None:
        self._needs = needs

    @Get("/")
    def index(self) -> dict[str, str]:
        return {"status": "ok"}


@Module(controllers=[BrokenController], providers=[NeedsUnregistered])
class AppModule:
    pass
"""


def _write_module(directory: Path, name: str, source: str) -> Path:
    """Write one importable module into a directory and return its path."""

    path = directory / f"{name}.py"
    path.write_text(source.lstrip(), encoding="utf-8")
    return path


def _run(argv: list[str], import_root: Path) -> int:
    """Run the CLI with a directory on the import path, and put the path back."""

    original_path = list(sys.path)
    sys.path.insert(0, str(import_root))
    try:
        return cli_main_module.main(argv)
    finally:
        sys.path[:] = original_path


def test_version_reports_the_packaged_version(capsys) -> None:
    assert cli_main_module.main(["--version"]) == 0

    printed = capsys.readouterr().out.strip()
    assert printed == f"bustan {importlib.metadata.version('bustan')}"


def test_doctor_reports_every_changed_construct_with_a_fix(tmp_path: Path, capsys) -> None:
    _write_module(tmp_path, "legacy_project", _LEGACY_SOURCE)

    exit_code = cli_main_module.main(["doctor", str(tmp_path)])

    assert exit_code == 1
    report = capsys.readouterr().out
    for construct in (
        "bustan.core.ioc.tokens",
        "bustan.logger.observability",
        "bustan.config.config_service",
        "bustan.platform.http.execution",
        "bustan.adapters.asgi.RequestBodyTooLarge",
        "ThrottlerStorage.increment",
        "ThrottlerStorage.get_ttl",
        "MetricsSink.record_request",
        "TraceSpan.finish",
        "RequestTracer.start_span",
        "RateLimit",
    ):
        assert construct in report

    # Every finding carries the edit that answers it, not only the name of the problem.
    assert report.count("fix: ") == report.count("what changed: ")
    assert "Import bustan.kernel.ioc.tokens instead." in report
    assert "Import RequestBodyTooLargeError from bustan.errors instead." in report
    assert "async def count_request(self, key: str, ttl: int, limit: int)" in report


def test_doctor_reports_nothing_for_a_project_already_on_two_zero(tmp_path: Path, capsys) -> None:
    _write_module(tmp_path, "modern_project", _MODERN_SOURCE)

    exit_code = cli_main_module.main(["doctor", str(tmp_path)])

    assert exit_code == 0
    assert "nothing to change" in capsys.readouterr().out


def test_doctor_renders_findings_as_json(tmp_path: Path, capsys) -> None:
    _write_module(tmp_path, "legacy_json_project", _LEGACY_SOURCE)

    assert cli_main_module.main(["doctor", str(tmp_path), "--format", "json"]) == 1

    report = json.loads(capsys.readouterr().out)
    assert report["summary"] == [
        {"scanned": 1, "files": 1, "findings": len(report["findings"]), "skipped": 0}
    ]
    first = report["findings"][0]
    assert set(first) == {"file", "line", "construct", "change", "fix"}
    assert first["file"] == "legacy_json_project.py"


def test_doctor_reports_a_file_it_cannot_parse(tmp_path: Path, capsys) -> None:
    (tmp_path / "unparseable.py").write_text("def broken(:\n", encoding="utf-8")

    assert cli_main_module.main(["doctor", str(tmp_path)]) == 0

    report = capsys.readouterr().out
    assert "unparseable.py  could not be parsed" in report
    assert "1 file not parsed" in report


def test_doctor_does_not_descend_into_a_virtual_environment(tmp_path: Path) -> None:
    vendored = tmp_path / ".venv" / "lib"
    vendored.mkdir(parents=True)
    _write_module(vendored, "vendored_legacy", _LEGACY_SOURCE)
    _write_module(tmp_path, "own_code", _MODERN_SOURCE)

    result = scan_path(tmp_path)

    assert result.scanned == 1
    assert result.findings == ()


def test_doctor_scans_a_single_file(tmp_path: Path) -> None:
    module_path = _write_module(tmp_path, "one_legacy_file", _LEGACY_SOURCE)

    result = scan_path(module_path)

    assert result.scanned == 1
    assert {finding.path for finding in result.findings} == {str(module_path)}


def test_doctor_reports_a_path_that_does_not_exist(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "absent"

    assert cli_main_module.main(["doctor", str(missing)]) == 1
    assert f"Nothing to scan at {missing}" in capsys.readouterr().err


def test_graph_renders_the_compiled_graph_in_both_formats(tmp_path: Path, capsys) -> None:
    _write_module(tmp_path, "graph_project", _BARE_APPLICATION_SOURCE)

    assert _run(["graph", "graph_project:AppModule"], tmp_path) == 0
    table = capsys.readouterr().out
    assert "modules (1)" in table
    assert "BareController" in table

    assert _run(["graph", "graph_project:AppModule", "--format", "json"], tmp_path) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["modules"][0]["module"] == "AppModule"
    assert report["modules"][0]["controllers"] == ["BareController"]
    assert report["providers"] == []


def test_graph_names_a_built_module_without_the_values_it_was_built_with(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    env_file = tmp_path / "graph.env"
    env_file.write_text("GRAPH_SECRET_VALUE=meridian\n", encoding="utf-8")
    monkeypatch.delenv("GRAPH_SECRET_VALUE", raising=False)
    _write_module(
        tmp_path,
        "graph_config_project",
        _APPLICATION_SOURCE.replace("$env_file", str(env_file)),
    )

    assert _run(["graph", "graph_config_project:AppModule"], tmp_path) == 0

    report = capsys.readouterr().out
    assert "_ConfigModuleBase (dynamic)" in report
    assert "meridian" not in report


def test_config_withholds_a_configured_secret(tmp_path: Path, capsys, monkeypatch) -> None:
    env_file = tmp_path / "config.env"
    env_file.write_text(
        "APP_NAME=demo\nDATABASE_PASSWORD=orchard\nAPI_KEY=cloudberry\n", encoding="utf-8"
    )
    for name in ("APP_NAME", "DATABASE_PASSWORD", "API_KEY"):
        monkeypatch.delenv(name, raising=False)
    _write_module(
        tmp_path, "config_project", _APPLICATION_SOURCE.replace("$env_file", str(env_file))
    )

    assert _run(["config", "config_project:AppModule"], tmp_path) == 0

    report = capsys.readouterr().out
    assert "orchard" not in report
    assert "cloudberry" not in report
    assert "DATABASE_PASSWORD" in report
    assert "APP_NAME" in report
    assert "demo" in report


def test_config_prints_the_values_when_redaction_is_declined(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    env_file = tmp_path / "revealed.env"
    env_file.write_text("DATABASE_PASSWORD=orchard\n", encoding="utf-8")
    monkeypatch.delenv("DATABASE_PASSWORD", raising=False)
    _write_module(
        tmp_path, "revealed_project", _APPLICATION_SOURCE.replace("$env_file", str(env_file))
    )

    assert _run(["config", "revealed_project:AppModule", "--no-redacted"], tmp_path) == 0

    assert "orchard" in capsys.readouterr().out


def test_config_renders_json_a_script_can_parse(tmp_path: Path, capsys, monkeypatch) -> None:
    env_file = tmp_path / "json.env"
    env_file.write_text("SERVICE_TOKEN=juniper\n", encoding="utf-8")
    monkeypatch.delenv("SERVICE_TOKEN", raising=False)
    _write_module(
        tmp_path, "config_json_project", _APPLICATION_SOURCE.replace("$env_file", str(env_file))
    )

    assert _run(["config", "config_json_project:AppModule", "--format", "json"], tmp_path) == 0

    report = json.loads(capsys.readouterr().out)
    values = {row["key"]: row["value"] for row in report["config"]}
    assert values["SERVICE_TOKEN"] == "[redacted]"


def test_config_reports_an_application_that_resolves_no_configuration(
    tmp_path: Path, capsys
) -> None:
    _write_module(tmp_path, "unconfigured_project", _BARE_APPLICATION_SOURCE)

    assert _run(["config", "unconfigured_project:AppModule"], tmp_path) == 1
    assert "ConfigModule.for_root()" in capsys.readouterr().err


def test_config_refuses_a_configuration_that_is_not_a_mapping(monkeypatch, capsys) -> None:
    monkeypatch.setattr(config_command, "_create_app", lambda *args, **kwargs: _NotAMapping())
    monkeypatch.setattr(config_command, "_load_root_module", lambda target: object)

    exit_code = config_command.run_config_command(
        argparse.Namespace(target="anything:AppModule", redacted=True, output_format="table")
    )

    assert exit_code == 1
    assert "not to a mapping of values" in capsys.readouterr().err


class _NotAMapping:
    """An application whose configuration token answers with something unusable."""

    def get(self, token: object) -> object:
        return "a string is not a mapping of values"


def test_redaction_widens_the_shared_defaults_to_prefixed_keys() -> None:
    keys = config_command.redaction_keys(
        {"DATABASE_PASSWORD": "orchard", "APP_NAME": "demo", "TOKEN": "juniper"}
    )

    assert "database_password" in keys
    assert "token" in keys
    assert "app_name" not in keys


@pytest.mark.parametrize(
    "command",
    [
        ["routes", "snapshot", "unresolvable_project:AppModule"],
        ["governance", "ownership", "unresolvable_project:AppModule"],
        ["graph", "unresolvable_project:AppModule"],
        ["config", "unresolvable_project:AppModule"],
    ],
)
def test_a_provider_resolution_failure_is_reported_rather_than_raised(
    command: list[str], tmp_path: Path, capsys
) -> None:
    _write_module(tmp_path, "unresolvable_project", _UNRESOLVABLE_SOURCE)

    exit_code = _run(command, tmp_path)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Traceback" not in captured.err
    assert "which AppModule cannot see" in captured.err


def test_main_reports_a_framework_error_a_command_did_not_catch(monkeypatch, capsys) -> None:
    from bustan.kernel.errors import ProviderResolutionError

    def raise_error(_arguments: argparse.Namespace) -> int:
        raise ProviderResolutionError("the container refused")

    monkeypatch.setitem(cli_main_module._HANDLERS, "doctor", raise_error)

    assert cli_main_module.main(["doctor"]) == 1
    assert "the container refused" in capsys.readouterr().err


def test_a_failure_with_no_message_still_says_something(capsys) -> None:
    from bustan.cli.services.failures import report_failure

    assert report_failure(ValueError()) == 1
    assert capsys.readouterr().err.strip() == "ValueError"


def test_a_table_aligns_its_columns_and_names_an_empty_section() -> None:
    rendered = reporting.render_table(
        (
            reporting.ReportSection(
                key="rows",
                title="rows",
                columns=("name", "tags", "global"),
                rows=(
                    {"name": "alpha", "tags": ("one", "two"), "global": True},
                    {"name": "a-much-longer-name", "tags": (), "global": False},
                ),
            ),
            reporting.ReportSection(key="empty", title="empty", columns=("name",), rows=()),
        )
    )

    lines = rendered.splitlines()
    assert lines[0] == "rows (2)"
    assert lines[1] == "name                tags      global"
    assert lines[3].startswith("alpha               one, two  yes")
    assert lines[4].endswith("no")
    assert lines[-2:] == ["empty (0)", "(none)"]


def test_a_cell_spells_out_the_values_a_reader_could_misread() -> None:
    assert reporting.render_cell(None) == "-"
    assert reporting.render_cell(()) == "-"
    assert reporting.render_cell("") == "-"
    assert reporting.render_cell(True) == "yes"
    assert reporting.render_cell(0) == "0"


def test_the_format_option_defaults_to_the_table() -> None:
    parser = argparse.ArgumentParser()
    reporting.add_format_option(parser)

    assert parser.parse_args([]).output_format == reporting.TABLE_FORMAT
    assert parser.parse_args(["--format", "json"]).output_format == reporting.JSON_FORMAT


def test_the_scan_leaves_alone_what_it_cannot_read_from_the_source(tmp_path: Path) -> None:
    (tmp_path / "quiet.py").write_text(
        "from . import sibling\n"
        "from bustan.adapters.asgi import AsgiAdapter\n"
        "from bustan.security import policy\n"
        "\n"
        "\n"
        "class ModernSink:\n"
        "    def record_request(self, *, labels, duration_seconds: float) -> None:\n"
        "        return None\n"
        "\n"
        "\n"
        "@policy.RateLimit(limit=1, window=WINDOW)\n"
        "def handler() -> None:\n"
        "    return None\n"
        "\n"
        "\n"
        '@DECORATORS["rate"](limit=1, window="a fortnight")\n'
        "def reached_through_a_lookup() -> None:\n"
        "    return None\n",
        encoding="utf-8",
    )

    assert scan_path(tmp_path).findings == ()


def test_the_scan_sees_a_decorator_reached_through_its_module(tmp_path: Path) -> None:
    (tmp_path / "qualified.py").write_text(
        "from bustan.security import policy\n"
        "\n"
        "\n"
        '@policy.RateLimit(limit=1, window="a fortnight")\n'
        "def handler() -> None:\n"
        "    return None\n",
        encoding="utf-8",
    )

    findings = scan_path(tmp_path).findings

    assert [finding.construct for finding in findings] == ["RateLimit"]
    assert "'a fortnight' cannot be read" in findings[0].fix
