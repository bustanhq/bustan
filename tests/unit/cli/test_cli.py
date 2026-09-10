"""Unit tests for the Bustan CLI init command."""

import argparse
import ast
import builtins
import importlib
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from string import Template
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

import bustan.cli.main as cli_main_module
from bustan.cli.commands import governance as governance_commands
from bustan.cli.commands import routes as routes_commands
from bustan.cli.commands.init import register_init_command, run_init_command
from bustan.cli.services import scaffold as scaffold_service
from bustan.kernel.module.dynamic import ModuleInstanceKey

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
    (directory / "pyproject.toml").write_text(_PYPROJECT_TOML.format(name=name), encoding="utf-8")


def _init(directory: Path, *arguments: str) -> int:
    """Run the init command in *directory* through a parser that declares its flags."""

    parser = argparse.ArgumentParser(prog="bustan")
    register_init_command(parser.add_subparsers(dest="command"))
    parsed = parser.parse_args(["init", *arguments])

    old_cwd = os.getcwd()
    os.chdir(directory)
    try:
        return run_init_command(parsed)
    finally:
        os.chdir(old_cwd)


def test_init_creates_expected_files(tmp_path: Path, capsys) -> None:
    _write_pyproject(tmp_path, "hello-bustan")
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        exit_code = cli_main_module.main(["init"])
    finally:
        os.chdir(old_cwd)

    assert exit_code == 0
    assert (tmp_path / "README.md").exists()
    pkg = tmp_path / "src" / "hello_bustan"
    assert (pkg / "__init__.py").exists()
    assert (pkg / "app_main.py").exists()
    assert (pkg / "app_module.py").exists()
    assert (pkg / "app_controller.py").exists()
    assert (pkg / "app_service.py").exists()
    tests = tmp_path / "tests" / "hello_bustan"
    assert (tests / "test_app_controller.py").exists()
    assert (tests / "test_app_service.py").exists()
    assert (tests / "test_app_module.py").exists()
    stdout = capsys.readouterr().out
    assert "hello_bustan" in stdout
    # Every path written is named, because this is the only command that writes files
    # and the reader has to be able to see what landed where without listing the tree.
    assert "src/hello_bustan/app_main.py" in stdout
    assert "tests/hello_bustan/test_app_module.py" in stdout
    assert "uv sync" in stdout
    assert "uv run start" in stdout
    assert "uv run dev" in stdout


def _uv_commands(text: str) -> list[str]:
    """Return every uv command line in text, indentation and fencing removed."""

    return [line.strip() for line in text.splitlines() if line.strip().startswith("uv ")]


def _install_commands(commands: list[str]) -> list[str]:
    """Return the commands that install dependencies, in the order they were given."""

    return [command for command in commands if command.startswith(("uv sync", "uv add"))]


def test_scaffolded_readme_gives_the_same_commands_init_prints(tmp_path: Path, capsys) -> None:
    _write_pyproject(tmp_path, "hello-bustan")
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        assert cli_main_module.main(["init"]) == 0
    finally:
        os.chdir(old_cwd)

    printed = _uv_commands(capsys.readouterr().out)
    written = _uv_commands((tmp_path / "README.md").read_text(encoding="utf-8"))

    # The terminal output scrolls away and the README is the copy the user keeps, so the
    # two have to name one install command, not two. The install lines are compared as a
    # whole rather than searched for: a README that adds an install step the command did
    # not name, or drops the one it did, describes a project nobody receives, and only an
    # exact comparison catches that.
    assert _install_commands(written) == _install_commands(printed) == ["uv sync"]
    # Everything else the command offers as a next step is documented too.
    assert set(printed) <= set(written)


# Installed alongside a scaffolded project's tests to hide the HTTP client packages
# that starlette's own test client needs. A scaffolded manifest declares bustan with the
# transport extra, plus ty, ruff and pytest, and nothing else, so a generated test that
# only passes because one of these happens to be present in the developing environment
# is not passing for a user, and this plugin makes that difference visible here.
_NO_HTTP_CLIENT_PLUGIN = """\
import sys
from importlib.abc import MetaPathFinder

HIDDEN = frozenset({"httpx", "httpx2"})


class _HideHttpClients(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] in HIDDEN:
            raise ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)
        return None


for name in [name for name in sys.modules if name.partition(".")[0] in HIDDEN]:
    del sys.modules[name]
sys.meta_path.insert(0, _HideHttpClients())
"""


def _run_scaffolded_tests(tmp_path: Path) -> tuple[ElementTree.Element | None, str]:
    """Run a scaffolded project's own tests with no HTTP client package available."""

    plugin_directory = tmp_path / "no_http_client_plugin"
    plugin_directory.mkdir()
    (plugin_directory / "no_http_client.py").write_text(_NO_HTTP_CLIENT_PLUGIN, encoding="utf-8")

    report_path = tmp_path / "junit.xml"
    environment = dict(os.environ)
    environment.pop("PYTEST_ADDOPTS", None)
    environment["PYTHONPATH"] = os.pathsep.join([str(plugin_directory), str(tmp_path / "src")])
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-p",
            "no_http_client",
            "--ignore",
            str(plugin_directory),
            f"--junit-xml={report_path}",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    suite = ElementTree.parse(report_path).getroot().find("testsuite")
    return suite, completed.stdout


def test_init_writes_tests_pytest_can_collect_and_run(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, "hello-bustan")
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        assert cli_main_module.main(["init"]) == 0
    finally:
        os.chdir(old_cwd)

    suite, output = _run_scaffolded_tests(tmp_path)

    assert suite is not None, output
    assert suite.get("tests") == "3", output
    assert suite.get("errors") == "0", output
    # A scaffolded project installs no HTTP client package, so a generated test that
    # reaches for one fails rather than erroring; both counts have to be zero for the
    # generated suite to be one a user can actually run.
    assert suite.get("failures") == "0", output
    # The collection above is what proves it; this states the cause. An __init__.py here
    # would make tests/<package_name> importable as <package_name>, and pytest's default
    # import mode puts its parent first on sys.path, shadowing src/<package_name>.
    assert not (tmp_path / "tests" / "hello_bustan" / "__init__.py").exists()


def test_scaffolded_project_needs_no_reformatting(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, "hello-bustan")
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        assert cli_main_module.main(["init"]) == 0
    finally:
        os.chdir(old_cwd)

    # The templates are excluded from this repository's own formatter run, and they have
    # to be: three of them hold a placeholder and are not parseable Python until the
    # scaffolder substitutes it. So the only place the formatter can see them is here,
    # after substitution, over the tree a user actually receives. Asserting on the
    # rendered output rather than on the template files also means a template added
    # later is covered without anyone remembering to list it.
    #
    # --isolated pins the run to the formatter's default settings, which is what a
    # scaffolded project gets: it carries no formatter configuration of its own, and
    # without this the result would depend on whatever configuration happens to sit
    # above the temporary directory. Those defaults include a line length of 88, which
    # is shorter than the one this repository formats itself at, so a template line
    # between the two widths is rejected here and accepted everywhere else. That is the
    # strictness a scaffolded project is actually measured by, and the templates have
    # to be written to fit it rather than to fit this repository's own setting.
    completed = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", "--isolated", "."],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


# The rule set a scaffolded project is measured against here. It is written out rather
# than left to the linter's defaults on purpose: a scaffolded project carries no linter
# configuration, so it is judged by whichever defaults the release its owner installed
# happens to ship, and those defaults change between releases. The linter reachable from
# this suite is the one this repository pins, which is older than the one a new project
# installs, so a guard that inherited defaults would be measuring a different, weaker
# rule set than the one users are held to and would report clean while they were not.
# Naming the rules makes the guard mean the same thing under every version, and makes
# widening it a decision someone takes rather than something an upgrade does silently.
#
# The list is the same one this repository lints itself with. Import order, `I`, is the
# rule the templates actually failed, but there is no reason to hold code this project
# ships to a lower standard than code it keeps, and the set is a superset of the linter
# defaults a new project gets today, so passing here means passing there.
_SCAFFOLDED_PROJECT_LINT_RULES = ("E", "F", "W", "I", "UP", "B", "SIM")


def test_scaffolded_project_passes_lint(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, "hello-bustan")
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        assert cli_main_module.main(["init"]) == 0
    finally:
        os.chdir(old_cwd)

    # The scaffolded README tells a new project's owner to lint it, so the tree the
    # scaffolder writes has to survive that command. The templates are excluded from
    # this repository's own lint run and have to be, because three of them hold a
    # placeholder and are not parseable Python until the scaffolder substitutes it, so
    # the rendered project in a temporary directory is the only place they can be
    # linted at all. Checking the rendered output rather than the template files also
    # covers a template added later without anyone remembering to list it.
    #
    # --isolated pins the run to explicit settings instead of whatever configuration
    # sits above the temporary directory, and with it the line length is the linter's
    # own default of 88, which is shorter than the width this repository uses. That is
    # the width a scaffolded project is measured at, so the templates are written to
    # fit it.
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--isolated",
            "--select",
            ",".join(_SCAFFOLDED_PROJECT_LINT_RULES),
            ".",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_TEMPLATES_ROOT = _REPOSITORY_ROOT / "src" / "bustan" / "cli" / "templates"
_STABILITY_GUIDE = _REPOSITORY_ROOT / "docs" / "reference" / "stability.md"


def _documented_modules(section_heading: str) -> frozenset[str]:
    """Collect the module names the stability guide bullets under one heading."""

    collected: set[str] = set()
    in_section = False
    for line in _STABILITY_GUIDE.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            in_section = line.strip() == section_heading
            continue
        if not in_section:
            continue
        bullet = re.fullmatch(r"- `([A-Za-z0-9_.*]+)`", line.strip())
        if bullet is not None:
            collected.add(bullet.group(1).removesuffix(".*"))
    return frozenset(collected)


def _template_package_imports() -> tuple[tuple[Path, str], ...]:
    """Return every bustan module the templates import, paired with the file doing it."""

    # Three templates hold placeholders and are not parseable Python until they are
    # substituted, so a stand-in is substituted here for the same reason the scaffolder
    # substitutes the real one. The values only have to parse; nothing reads them back.
    placeholders = {"project_name": "Example Project", "package_name": "example_app"}
    imports: list[tuple[Path, str]] = []
    for template_path in sorted(_TEMPLATES_ROOT.rglob("*.py")):
        source = Template(template_path.read_text(encoding="utf-8")).safe_substitute(placeholders)
        for node in ast.walk(ast.parse(source, filename=str(template_path))):
            if isinstance(node, ast.Import):
                imports.extend((template_path, alias.name) for alias in node.names)
            # A relative import names a module inside the scaffolded project, never one
            # of ours, so only absolute imports are of interest here.
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
                imports.append((template_path, node.module))
    return tuple((path, module) for path, module in imports if module.split(".")[0] == "bustan")


def _describe_unsupported_import(path: Path, module: str, internal: frozenset[str]) -> str:
    """Name an unsupported import and, where the guide lists one, its internal namespace."""

    # The guide's rule is that everything outside the supported modules is internal
    # whether or not its hand-maintained list has caught up, so an import matching no
    # listed namespace is still reported, just without one to point at.
    namespace = next(
        (name for name in sorted(internal) if module == name or module.startswith(f"{name}.")),
        None,
    )
    location = f"{path.relative_to(_REPOSITORY_ROOT).as_posix()} imports {module}"
    return location if namespace is None else f"{location} ({namespace} is internal)"


def test_templates_import_only_the_supported_public_surface() -> None:
    # Everything under the templates directory is shipped into a user's project and is
    # excluded from this repository's own lint, type and coverage runs, so this is the
    # only place the imports a user is handed are checked at all. The rule is the
    # stability guide's: compatibility is promised for the modules it lists as
    # supported, and every other namespace may be restructured without notice, so a
    # template that reaches into one hands a new project a test that can break under an
    # upgrade it did not ask for. The guide is read rather than restated here, so a
    # namespace promoted or demoted there moves this check with it.
    supported = _documented_modules("## Supported Public Surface")
    internal = _documented_modules("## Internal Modules")
    assert supported, "no supported module parsed out of the stability guide"
    assert internal, "no internal namespace parsed out of the stability guide"
    assert not supported & internal, "the stability guide lists a module as both"

    package_imports = _template_package_imports()
    assert package_imports, "no bustan import was found in the templates"

    offenders = sorted(
        _describe_unsupported_import(path, module, internal)
        for path, module in package_imports
        if module not in supported
    )
    assert offenders == [], (
        "templates may only import "
        + ", ".join(sorted(supported))
        + "; found "
        + "; ".join(offenders)
    )


def test_init_adds_scripts_to_pyproject(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, "my-app")
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        cli_main_module.main(["init"])
    finally:
        os.chdir(old_cwd)

    manifest = tomllib.loads((tmp_path / "pyproject.toml").read_text(encoding="utf-8"))
    # Both scripts name the module the scaffold owns rather than the package, so that a
    # package whose __init__.py came from somewhere else keeps the main it already meant.
    assert manifest["project"]["scripts"]["start"] == "my_app.app_main:main"
    assert manifest["project"]["scripts"]["dev"] == "my_app.app_main:dev"


def test_init_declares_the_transport_so_one_sync_can_serve(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, "my-app")

    assert _init(tmp_path) == 0

    manifest = tomllib.loads((tmp_path / "pyproject.toml").read_text(encoding="utf-8"))
    # Serving needs a transport. The manifest declares the extra rather than the command
    # printing a second install step, so the `uv sync` it does print is enough to serve.
    declared = manifest["project"]["dependencies"]
    assert [entry for entry in declared if entry.startswith("bustan[starlette]>=")] == declared
    assert manifest["dependency-groups"]["dev"] == ["pytest", "ruff", "ty"]


def test_package_name_from_pyproject_returns_none_for_blank_project_name(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "   "\n', encoding="utf-8")

    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        assert scaffold_service.package_name_from_pyproject() is None
    finally:
        os.chdir(old_cwd)


_BUILD_SYSTEM = '[build-system]\nrequires = ["uv_build"]\nbuild-backend = "uv_build"\n'


def test_init_project_preserves_existing_readme_and_scripts_section(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo-app"\ndependencies = []\n\n'
        '[project.scripts]\ncustom = "demo_app:main"\n\n' + _BUILD_SYSTEM,
        encoding="utf-8",
    )
    readme_path = tmp_path / "README.md"
    readme_path.write_text("keep me\n", encoding="utf-8")

    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        scaffold_service.init_project(package_name="demo_app")
    finally:
        os.chdir(old_cwd)

    assert readme_path.read_text(encoding="utf-8") == "keep me\n"
    pyproject_content = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert pyproject_content.count("[project.scripts]") == 1
    scripts = tomllib.loads(pyproject_content)["project"]["scripts"]
    # uv init --package pre-creates [project.scripts]; start and dev must be merged into
    # it rather than skipped, and the entry the project already declared must survive.
    assert scripts == {
        "custom": "demo_app:main",
        "start": "demo_app.app_main:main",
        "dev": "demo_app.app_main:dev",
    }


def test_init_project_does_not_duplicate_existing_start_and_dev_scripts(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo-app"\ndependencies = ["bustan[starlette]"]\n\n'
        '[project.scripts]\nstart = "demo_app:serve"\ndev = "demo_app:watch"\n\n'
        "[dependency-groups]\ndev = []\n\n" + _BUILD_SYSTEM,
        encoding="utf-8",
    )
    before = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")

    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        report = scaffold_service.init_project(package_name="demo_app")
    finally:
        os.chdir(old_cwd)

    # A manifest that already declares everything is not rewritten at all. The entries
    # it declared are the project's own, so a script pointing somewhere else stays
    # pointing there rather than being redirected at what this would have written.
    assert report.manifest_edits == ()
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == before


def test_scaffold_helpers_sanitize_project_names(tmp_path: Path) -> None:
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        assert scaffold_service.package_name_from_pyproject() is None
    finally:
        os.chdir(old_cwd)

    assert not (tmp_path / "pyproject.toml").exists()
    assert scaffold_service._to_package_name("!!!") == "bustan_app"
    assert scaffold_service._to_package_name("123 app") == "app_123_app"


def test_init_fails_without_pyproject(tmp_path: Path, capsys) -> None:
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        exit_code = cli_main_module.main(["init"])
    finally:
        os.chdir(old_cwd)

    assert exit_code == 1
    assert "pyproject.toml" in capsys.readouterr().err


def _tree_state(directory: Path) -> dict[str, str]:
    """Return every file under *directory* by relative path, with its contents."""

    return {
        path.relative_to(directory).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_second_init_changes_no_existing_file_and_names_each_one(tmp_path: Path, capsys) -> None:
    _write_pyproject(tmp_path, "demo-app")
    assert _init(tmp_path) == 0
    handler = tmp_path / "src" / "demo_app" / "app_service.py"
    handler.write_text("# a week of work\n", encoding="utf-8")
    before = _tree_state(tmp_path)
    capsys.readouterr()

    assert _init(tmp_path) == 0

    # The loss this prevents is unrecoverable outside version control, so the guard is
    # the whole tree rather than the one file: nothing the first run wrote, and nothing
    # written over it since, may differ afterwards.
    assert _tree_state(tmp_path) == before
    stdout = capsys.readouterr().out
    for path in before:
        if path.startswith(("src/", "tests/")) or path == "README.md":
            assert path in stdout


def test_init_force_replaces_a_file_that_exists(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, "demo-app")
    assert _init(tmp_path) == 0
    handler = tmp_path / "src" / "demo_app" / "app_service.py"
    scaffolded = handler.read_text(encoding="utf-8")
    handler.write_text("# replaced by hand\n", encoding="utf-8")

    assert _init(tmp_path, "--force") == 0

    assert handler.read_text(encoding="utf-8") == scaffolded


def test_init_gives_a_dev_script_to_a_project_carrying_a_dev_dependency_group(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo-app"\ndependencies = []\n\n'
        '[dependency-groups]\ndev = ["pytest"]\n\n' + _BUILD_SYSTEM,
        encoding="utf-8",
    )

    assert _init(tmp_path) == 0

    manifest = tomllib.loads((tmp_path / "pyproject.toml").read_text(encoding="utf-8"))
    # `uv add --dev` writes a `dev` key under [dependency-groups]. It declares a
    # dependency group, not a script, so the lookup is scoped to [project.scripts] and
    # a project carrying one still gets the script the printed next steps name.
    assert manifest["project"]["scripts"]["dev"] == "demo_app.app_main:dev"
    assert manifest["dependency-groups"]["dev"] == ["pytest"]


def test_init_leaves_a_manifest_valid_when_a_value_reads_like_a_table_header(
    tmp_path: Path,
) -> None:
    description = "declares [project.scripts] and [dependency-groups] in prose"
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "demo-app"\ndescription = "{description}"\n'
        "dependencies = []\n\n" + _BUILD_SYSTEM,
        encoding="utf-8",
    )

    assert _init(tmp_path) == 0

    # Editing the manifest as text is what corrupted it: a value that reads like a
    # section header is not one, and only the parsed tables can tell the difference.
    manifest = tomllib.loads((tmp_path / "pyproject.toml").read_text(encoding="utf-8"))
    assert manifest["project"]["description"] == description
    assert manifest["project"]["scripts"]["start"] == "demo_app.app_main:main"


def test_init_refuses_a_project_with_no_build_system(tmp_path: Path, capsys) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo-app"\ndependencies = []\n', encoding="utf-8"
    )

    assert _init(tmp_path) == 1

    stderr = capsys.readouterr().err
    assert "[build-system]" in stderr
    assert "uv init --package" in stderr
    # Nothing is written, because uv exposes no script from a project it cannot build
    # and a scaffold whose entry points cannot be reached is worse than none.
    assert not (tmp_path / "src").exists()


def test_init_reports_a_malformed_manifest_without_a_traceback(tmp_path: Path, capsys) -> None:
    (tmp_path / "pyproject.toml").write_text('[project\nname = "demo-app"\n', encoding="utf-8")

    assert _init(tmp_path) == 1

    captured = capsys.readouterr()
    assert "pyproject.toml" in captured.err
    assert "valid TOML" in captured.err
    assert "Traceback" not in captured.err + captured.out


def test_init_adds_the_transport_to_a_multi_line_dependency_array(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo-app"\ndependencies = [\n  "httpx>=0.28",\n]\n\n' + _BUILD_SYSTEM,
        encoding="utf-8",
    )

    assert _init(tmp_path) == 0

    content = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    manifest = tomllib.loads(content)
    assert manifest["project"]["dependencies"][1:] == ["httpx>=0.28"]
    # The entry joins the array the way the entries already in it are written, so the
    # manifest a project keeps does not come back reflowed by a command it ran once.
    assert '  "bustan[starlette]>=' in content


def test_init_declares_dependencies_where_the_manifest_names_none(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo-app"\nversion = "0.1.0"\n\n' + _BUILD_SYSTEM,
        encoding="utf-8",
    )

    assert _init(tmp_path) == 0

    lines = (tmp_path / "pyproject.toml").read_text(encoding="utf-8").splitlines()
    manifest = tomllib.loads("\n".join(lines))
    assert len(manifest["project"]["dependencies"]) == 1
    # The key joins the table it belongs to rather than displacing the first key in it.
    assert lines.index('version = "0.1.0"') < lines.index(
        next(line for line in lines if line.startswith("dependencies = "))
    )


def test_init_keeps_the_line_endings_the_manifest_was_written_with(tmp_path: Path) -> None:
    manifest_path = tmp_path / "pyproject.toml"
    manifest_path.write_bytes(
        ('[project]\nname = "demo-app"\ndependencies = []\n\n' + _BUILD_SYSTEM)
        .replace("\n", "\r\n")
        .encode("utf-8")
    )

    assert _init(tmp_path) == 0

    raw = manifest_path.read_bytes()
    # A manifest written on one platform and edited here must not come back with every
    # line changed, which is what a whole-file rewrite of its line endings would be.
    assert raw.count(b"\n") == raw.count(b"\r\n")
    assert tomllib.loads(raw.decode("utf-8"))["project"]["scripts"]["start"]


def test_init_refuses_a_manifest_whose_string_holds_a_bare_table_header(
    tmp_path: Path, capsys
) -> None:
    manifest = (
        '[project]\nname = "demo-app"\ndescription = """\n[project.scripts]\n"""\n'
        "dependencies = []\n\n" + _BUILD_SYSTEM
    )
    (tmp_path / "pyproject.toml").write_text(manifest, encoding="utf-8")

    assert _init(tmp_path) == 1

    # The only text in the file that reads exactly like a header is inside a string, so
    # there is no insertion point that leaves the rest of the file meaning what it did.
    # Refusing beats guessing: the manifest is untouched and the entries are named.
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == manifest
    assert not (tmp_path / "src").exists()
    stderr = capsys.readouterr().err
    assert 'start = "demo_app.app_main:main"' in stderr
    assert "[project.scripts]" in stderr


def test_init_refuses_a_manifest_whose_scripts_are_an_inline_table(tmp_path: Path, capsys) -> None:
    manifest = (
        '[project]\nname = "demo-app"\ndependencies = ["bustan[starlette]"]\n'
        'scripts = { custom = "demo_app:x" }\n\n'
        "[dependency-groups]\ndev = []\n\n" + _BUILD_SYSTEM
    )
    (tmp_path / "pyproject.toml").write_text(manifest, encoding="utf-8")

    assert _init(tmp_path) == 1

    # Appending a [project.scripts] header would define the table a second time and the
    # manifest would stop parsing, so the run is refused rather than the file broken.
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == manifest
    assert not (tmp_path / "src").exists()
    assert "by hand" in capsys.readouterr().err


def test_init_adds_only_what_the_manifest_is_missing(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo-app"\ndependencies = ["bustan[starlette]==2.0.0"]\n\n'
        '[project.scripts]\nstart = "demo_app.app_main:main"\n'
        'dev = "demo_app.app_main:dev"\n\n' + _BUILD_SYSTEM,
        encoding="utf-8",
    )

    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        report = scaffold_service.init_project(package_name="demo_app")
    finally:
        os.chdir(old_cwd)

    assert report.manifest_edits == ("added pytest, ruff, ty to the 'dev' dependency group",)
    # The pin the project chose is the project's, so it survives untouched.
    manifest = tomllib.loads((tmp_path / "pyproject.toml").read_text(encoding="utf-8"))
    assert manifest["project"]["dependencies"] == ["bustan[starlette]==2.0.0"]


def test_init_declares_dependencies_in_a_project_table_that_ends_the_file(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        _BUILD_SYSTEM + '\n[project]\nname = "demo-app"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )

    assert _init(tmp_path) == 0

    lines = (tmp_path / "pyproject.toml").read_text(encoding="utf-8").splitlines()
    assert len(tomllib.loads("\n".join(lines))["project"]["dependencies"]) == 1
    assert lines.index('version = "0.1.0"') < lines.index(
        next(line for line in lines if line.startswith("dependencies = "))
    )


def test_init_refuses_a_manifest_whose_dependencies_are_not_an_array(
    tmp_path: Path, capsys
) -> None:
    manifest = '[project]\nname = "demo-app"\ndependencies = { httpx = "*" }\n\n' + _BUILD_SYSTEM
    (tmp_path / "pyproject.toml").write_text(manifest, encoding="utf-8")

    assert _init(tmp_path) == 1

    # Declaring the dependency would define the key a second time and the manifest would
    # stop parsing. The result is parsed before it is written, which is what catches it.
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == manifest
    assert not (tmp_path / "src").exists()
    assert "by hand" in capsys.readouterr().err


def test_scaffold_refuses_an_insertion_point_it_cannot_locate() -> None:
    add = scaffold_service._with_transport_requirement
    requirement = "bustan[starlette]>=2.0.0"

    # A [project] table declared as root dotted keys has no header line to insert under,
    # and a dependencies line holding no array open has nowhere in it to insert. Neither
    # is guessed at: an insertion point that cannot be located refuses the edit.
    assert add('project.name = "demo-app"\n', requirement, {"dependencies": []}) is None
    assert add('[project]\nname = "demo-app"\n', requirement, {"dependencies": []}) is None
    assert add("[project]\ndependencies = truncated\n", requirement, {"dependencies": []}) is None


def test_scaffold_key_lookup_stops_at_the_next_table() -> None:
    lines = ["[project]\n", 'name = "demo-app"\n', "[tool.other]\n", "dependencies = []\n"]

    # A key of the same name in another table is a different setting entirely, and
    # editing it in place of the one asked for would change something nobody named.
    assert scaffold_service._key_index(lines, 0, "dependencies") is None
    assert scaffold_service._key_index(lines, 0, "name") == 1
    assert scaffold_service._key_index(lines[:2], 0, "dependencies") is None


def test_scaffold_compares_requirement_names_the_way_an_installer_does() -> None:
    names = scaffold_service._names_distribution
    assert names("Bustan[starlette]>=2", "bustan")
    assert names("bus_tan", "bus-tan")
    assert not names("bustanx", "bustan")
    # A manifest may hold anything; a non-string or an unparseable entry names nothing.
    assert not names(None, "bustan")
    assert not names("!!!", "bustan")


def test_init_help_says_what_is_written_and_that_existing_files_are_kept(capsys) -> None:
    parser = argparse.ArgumentParser(prog="bustan")
    register_init_command(parser.add_subparsers(dest="command"))

    with pytest.raises(SystemExit):
        parser.parse_args(["init", "--help"])

    help_text = capsys.readouterr().out
    assert "src/<package>" in help_text
    assert "tests/<package>" in help_text
    assert "kept" in help_text
    assert "--force" in help_text


def test_init_app_main_contains_bootstrap_and_scripts(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, "demo-app")

    assert _init(tmp_path) == 0

    content = (tmp_path / "src" / "demo_app" / "app_main.py").read_text(encoding="utf-8")
    assert "def bootstrap" in content
    assert "def main" in content
    assert "def dev" in content


def test_scaffolded_dev_script_hands_the_server_an_import_string(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, "demo-app")

    assert _init(tmp_path) == 0

    source = (tmp_path / "src" / "demo_app" / "app_main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "uvicorn.run"
    )
    keywords = {keyword.arg: keyword.value for keyword in call.keywords}

    # Reloading means owning the process, so it is the server's to do and not the
    # adapter's. It can only do it from a name it can import again in a fresh worker,
    # which an application already built is not.
    assert ast.literal_eval(call.args[0]) == "demo_app.app_main:create_asgi_app"
    assert ast.literal_eval(keywords["factory"]) is True
    assert ast.literal_eval(keywords["reload"]) is True

    # `listen` must not be asked to reload. The adapters refuse it, and the one that
    # once accepted it discarded it, which is the defect this replaces.
    listen = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("listen")
    )
    assert "reload" not in {keyword.arg for keyword in listen.keywords}


def test_main_prints_help_when_no_command_is_supplied(capsys) -> None:
    assert cli_main_module.main([]) == 1
    assert "usage:" in capsys.readouterr().out


def test_cli_import_does_not_require_optional_httpx(monkeypatch, capsys) -> None:
    real_import = builtins.__import__

    def fail_testclient_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "starlette.testclient":
            raise RuntimeError(
                "The starlette.testclient module requires the httpx package to be installed."
            )
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fail_testclient_import)

    original_main = sys.modules["bustan.cli.main"]
    original_governance = sys.modules["bustan.cli.commands.governance"]
    sys.modules.pop("bustan.cli.main", None)
    sys.modules.pop("bustan.cli.commands.governance", None)
    try:
        reloaded_main = importlib.import_module("bustan.cli.main")
        assert reloaded_main.main([]) == 1
    finally:
        sys.modules["bustan.cli.main"] = original_main
        sys.modules["bustan.cli.commands.governance"] = original_governance

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
        exit_code = cli_main_module.main(
            ["routes", "snapshot", "sample_app:AppModule", "--output", str(output)]
        )
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

    exit_code = cli_main_module.main(["routes", "diff", str(previous), str(current)])

    assert exit_code == 0
    diff = json.loads(capsys.readouterr().out)
    assert [entry["change"] for entry in diff] == ["removed", "added", "changed"]
    assert diff[2]["fields"] == ["path"]


def test_governance_ownership_reports_owner_and_deprecation_metadata(
    tmp_path: Path, capsys
) -> None:
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
        exit_code = cli_main_module.main(["governance", "ownership", "governance_app:AppModule"])
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
        exit_code = cli_main_module.main(
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
    exit_code = cli_main_module.main(["governance", "conformance", "starlette"])

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["adapter"] == "starlette"
    assert report["passed"] is True
    assert report["capabilities"]["supports_raw_body"] is True


def test_routes_and_governance_commands_report_missing_subcommands(capsys) -> None:
    assert routes_commands.run_routes_command(argparse.Namespace(routes_command=None)) == 1
    assert (
        governance_commands.run_governance_command(argparse.Namespace(governance_command=None)) == 1
    )

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
    assert (
        routes_commands.run_snapshot_command(argparse.Namespace(target="broken", output=None)) == 1
    )

    invalid_snapshot = tmp_path / "invalid.json"
    invalid_snapshot.write_text("{", encoding="utf-8")
    assert (
        routes_commands.run_diff_command(
            argparse.Namespace(previous=str(invalid_snapshot), current=str(invalid_snapshot))
        )
        == 1
    )

    assert (
        governance_commands._run_json_command(
            lambda *args: (_ for _ in ()).throw(ValueError("boom"))
        )
        == 1
    )

    captured = capsys.readouterr()
    assert "boom" in captured.err


def test_display_route_module_falls_back_to_repr_for_unknown_module_shape() -> None:
    contract = SimpleNamespace(module_key=SimpleNamespace(module="custom"))

    assert governance_commands._display_route_module(contract).startswith("namespace(")


def test_display_route_module_uses_nested_module_type_name() -> None:
    class UsersModule:
        pass

    contract = SimpleNamespace(module_key=ModuleInstanceKey(module=UsersModule, instance_id="test"))

    assert governance_commands._display_route_module(contract) == "UsersModule"
