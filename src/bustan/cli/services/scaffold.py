"""Service for scaffolding Bustan app files into an existing uv project.

The project written into may already hold work, so a file is written only where none
exists unless the caller asks for a replacement, and every path is reported either way.

The manifest is decided against its parsed tables and edited at insertion points found
line by line, then parsed again before it is written. Two things follow from that. A
value that merely reads like a table header is never mistaken for one, so a description
containing ``[project.scripts]`` cannot be turned into a section. And an edit that did
not land exactly as intended is refused rather than written, so the manifest a run
leaves behind always parses to what it parsed to before plus the entries named here.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any

from ..._version import get_installed_version
from ...kernel.errors import BustanError

_MANIFEST_NAME = "pyproject.toml"

# Serving HTTP needs a transport and the scaffolded application serves on the adapter
# this package ships, so the manifest declares that extra. Leaving it to the reader
# would mean the first `uv run start` of a fresh project fails on a missing web server.
_TRANSPORT_DISTRIBUTION = "bustan"
_TRANSPORT_EXTRA = "starlette"

# The tools the scaffolded README tells a new project's owner to run. They are declared
# rather than printed as a command to run afterwards, so that one `uv sync` leaves the
# project able to serve, test, lint and type-check without a further install step. No
# version bound: the lock file a project keeps is what pins these, and a bound written
# here would be a second, staler pin that only this command could update.
_DEVELOPMENT_TOOLS: tuple[str, ...] = ("pytest", "ruff", "ty")

# A table header of its own, which is the only form these edits recognise. A key whose
# value happens to contain the same text is not one, and neither is a dotted key.
_TABLE_HEADER = re.compile(r"^[ \t]*\[")

# Requirement strings name the same distribution when their names fold together, so
# they are compared the way an installer compares them rather than character by
# character: `Bustan`, `bustan` and `bus_tan` are one dependency, declared once.
_REQUIREMENT_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")
_NAME_SEPARATORS = re.compile(r"[-_.]+")


@dataclass(frozen=True, slots=True)
class ScaffoldReport:
    """What one run of the scaffolder did to the project in the current directory.

    ``written`` and ``skipped`` are paths relative to the project root. A path is
    skipped when a file is already there and the caller did not ask for it to be
    replaced, so a second run reports the whole scaffold as skipped and changes nothing.
    ``manifest_edits`` names each change made to the project manifest in plain English,
    and is empty where the manifest already declared everything a scaffolded project
    needs.
    """

    written: tuple[Path, ...]
    skipped: tuple[Path, ...]
    manifest_edits: tuple[str, ...]


def package_name_from_pyproject() -> str | None:
    """Read the project name from pyproject.toml in the current directory.

    Returns a name usable as a Python package, or ``None`` where there is no manifest
    or it names no project. A manifest that is not valid TOML is refused rather than
    reported as absent, because the two ask the reader to do different things.
    """

    manifest_path = Path.cwd() / _MANIFEST_NAME
    if not manifest_path.exists():
        return None

    _, manifest = _read_manifest(manifest_path)
    project_name = _table_of(manifest, "project").get("name", "")
    if not isinstance(project_name, str) or not project_name.strip():
        return None

    return _to_package_name(project_name)


def init_project(*, package_name: str, force: bool = False) -> ScaffoldReport:
    """Write Bustan app files into the current uv project and report what changed.

    A file that is already there is kept and reported as skipped, so a second run cannot
    destroy work; ``force`` replaces it instead. The manifest gains the transport
    dependency, the development tool group and the ``start`` and ``dev`` scripts wherever
    it does not already declare them.

    A project with no ``[build-system]`` table is refused before anything is written,
    because uv builds no package from one and so exposes neither script this writes.
    """

    cwd = Path.cwd()
    manifest_path = cwd / _MANIFEST_NAME
    manifest_text, manifest = _read_manifest(manifest_path)
    _require_build_system(manifest, manifest_path)

    # Both refusals the manifest can raise are settled before the first file is written,
    # so a manifest this command cannot edit leaves the project exactly as it was.
    edited_text, manifest_edits = _manifest_with_scaffold_entries(
        manifest_text, manifest, package_name, manifest_path
    )

    written, skipped = _write_source_files(cwd, package_name, force=force)
    if manifest_edits:
        manifest_path.write_text(edited_text, encoding="utf-8", newline="")

    return ScaffoldReport(written=written, skipped=skipped, manifest_edits=manifest_edits)


def _read_manifest(path: Path) -> tuple[str, dict[str, Any]]:
    """Return the manifest's text and its parsed tables, or say why it cannot be read.

    The text keeps the line endings the file was written with, so that a manifest
    written on one platform and edited here does not come back with every line changed.
    """

    text = path.read_text(encoding="utf-8", newline="")
    try:
        return text, tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise BustanError(
            f"{path} is not valid TOML: {error}. Fix the file, then re-run 'bustan init'."
        ) from error


def _require_build_system(manifest: Mapping[str, Any], path: Path) -> None:
    """Refuse a project uv cannot build, naming the command that gives it a build system."""

    if isinstance(manifest.get("build-system"), dict):
        return

    raise BustanError(
        f"{path} declares no [build-system], so uv builds no package from this project "
        "and would expose neither the 'start' nor the 'dev' script this writes. Create "
        "the project with 'uv init --package <name>', which declares one, or add a "
        "[build-system] table to the manifest, then re-run 'bustan init'."
    )


def _write_source_files(
    cwd: Path, package_name: str, *, force: bool
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Render every template into the project, keeping any file that is already there."""

    package_directory = cwd / "src" / package_name
    tests_directory = cwd / "tests" / package_name
    package_directory.mkdir(parents=True, exist_ok=True)
    tests_directory.mkdir(parents=True, exist_ok=True)

    substitutions = {
        "project_name": package_name.replace("_", " ").title(),
        "package_name": package_name,
    }
    templates_root = Path(__file__).parent.parent / "templates" / "app"

    written: list[Path] = []
    skipped: list[Path] = []
    for file_path, template_name in _template_targets(cwd, package_directory, tests_directory):
        if file_path.exists() and not force:
            skipped.append(file_path.relative_to(cwd))
            continue
        template = (templates_root / template_name).read_text(encoding="utf-8")
        file_path.write_text(Template(template).safe_substitute(substitutions), encoding="utf-8")
        written.append(file_path.relative_to(cwd))

    return tuple(written), tuple(skipped)


def _template_targets(
    cwd: Path, package_directory: Path, tests_directory: Path
) -> tuple[tuple[Path, str], ...]:
    """Pair every path the scaffold writes with the template it is rendered from."""

    # The tests directory is deliberately not a package. An __init__.py here would make
    # tests/<package_name> importable as <package_name>, and pytest's default import mode
    # puts its parent first on sys.path, so it would shadow src/<package_name> and the
    # generated tests could not import the code they test.
    return (
        (cwd / "README.md", "README.md"),
        (package_directory / "__init__.py", "app_init.py"),
        (package_directory / "app_main.py", "app_main.py"),
        (package_directory / "app_module.py", "app_module.py"),
        (package_directory / "app_controller.py", "app_controller.py"),
        (package_directory / "app_service.py", "app_service.py"),
        (tests_directory / "test_app_controller.py", "test_app_controller.py"),
        (tests_directory / "test_app_service.py", "test_app_service.py"),
        (tests_directory / "test_app_module.py", "test_app_module.py"),
    )


def _manifest_with_scaffold_entries(
    text: str, manifest: Mapping[str, Any], package_name: str, path: Path
) -> tuple[str, tuple[str, ...]]:
    """Return the manifest text a scaffolded project needs, and what it changed.

    The text is returned unchanged, with no edits reported, where the manifest already
    declares everything. Where an entry is missing and no safe insertion point exists,
    the run is refused with the entries named, so the reader can add them by hand.
    """

    project = _table_of(manifest, "project")
    requirement = _missing_transport_requirement(project)
    scripts = _missing_scripts(project, package_name)
    add_tools = _table_of(manifest, "dependency-groups").get("dev") is None
    if requirement is None and not scripts and not add_tools:
        return text, ()

    expected = _expected_manifest(text, requirement, scripts, add_tools=add_tools)
    edited: str | None = text
    if requirement is not None:
        edited = _with_transport_requirement(edited, requirement, project)
    if scripts and edited is not None:
        entries = [f'{key} = "{value}"' for key, value in scripts.items()]
        edited = _with_table_entries(edited, "project.scripts", entries, project.get("scripts"))
    if add_tools and edited is not None:
        entry = "dev = [" + ", ".join(f'"{tool}"' for tool in _DEVELOPMENT_TOOLS) + "]"
        edited = _with_table_entries(
            edited, "dependency-groups", [entry], manifest.get("dependency-groups")
        )
    if edited is None or not _parses_to(edited, expected):
        raise BustanError(_manual_edit_message(path, requirement, scripts, add_tools=add_tools))

    return edited, _describe_edits(requirement, scripts, add_tools=add_tools)


def _parses_to(text: str, expected: Mapping[str, Any]) -> bool:
    """Report whether *text* is a manifest that parses to exactly *expected*.

    This is what makes the line-by-line edits safe in general rather than in the cases
    anyone thought to enumerate. An insertion point found inside a multi-line string,
    or a key this edit would define twice, changes the parsed result or stops it
    parsing, and either way the edit is rejected before it can reach the file.
    """

    try:
        return tomllib.loads(text) == expected
    except tomllib.TOMLDecodeError:
        return False


def _missing_transport_requirement(project: Mapping[str, Any]) -> str | None:
    """Return the transport dependency to declare, or None where one is already declared.

    A manifest already naming this distribution keeps whatever it named, extra and
    version bound included: a project that has chosen a pin has chosen it deliberately,
    and replacing it would be a change nobody asked this command to make.
    """

    declared = project.get("dependencies")
    listed = declared if isinstance(declared, list) else []
    if any(_names_distribution(entry, _TRANSPORT_DISTRIBUTION) for entry in listed):
        return None
    extra = f"{_TRANSPORT_DISTRIBUTION}[{_TRANSPORT_EXTRA}]"
    return f"{extra}>={get_installed_version()}"


def _missing_scripts(project: Mapping[str, Any], package_name: str) -> dict[str, str]:
    """Return the console scripts [project.scripts] does not declare.

    The lookup is scoped to that table. A `dev` key anywhere else in the manifest, which
    is what `uv add --dev` writes under [dependency-groups], declares a dependency group
    rather than a script, and a project carrying one still needs the script.

    Both scripts name the module the scaffold writes the entry points into rather than
    the package itself, so that a package whose ``__init__.py`` was written by something
    else keeps whatever ``main`` it already meant.
    """

    declared = _table_of(project, "scripts")
    entry_point = f"{package_name}.app_main"
    wanted = {"start": f"{entry_point}:main", "dev": f"{entry_point}:dev"}
    return {key: value for key, value in wanted.items() if key not in declared}


def _expected_manifest(
    text: str,
    requirement: str | None,
    scripts: Mapping[str, str],
    *,
    add_tools: bool,
) -> dict[str, Any]:
    """Return the tables the manifest must parse to once the edits have landed."""

    expected = tomllib.loads(text)
    project: dict[str, Any] = expected.setdefault("project", {})
    if requirement is not None:
        declared = project.get("dependencies")
        project["dependencies"] = [requirement, *(declared if isinstance(declared, list) else [])]
    if scripts:
        project["scripts"] = {**scripts, **_table_of(project, "scripts")}
    if add_tools:
        groups: dict[str, Any] = expected.setdefault("dependency-groups", {})
        groups["dev"] = list(_DEVELOPMENT_TOOLS)
    return expected


def _with_transport_requirement(
    text: str, requirement: str, project: Mapping[str, Any]
) -> str | None:
    """Add *requirement* to [project] dependencies, or None where no insertion point holds."""

    lines = text.splitlines(keepends=True)
    header = _header_index(lines, "project")
    if header is None:
        return None

    entry = f'"{requirement}"'
    if not isinstance(project.get("dependencies"), list):
        declaration = f"dependencies = [{entry}]{_terminator(lines[header])}"
        lines.insert(_table_end(lines, header), declaration)
        return "".join(lines)

    index = _key_index(lines, header, "dependencies")
    if index is None:
        return None
    line = lines[index]
    opened = line.find("[")
    if opened == -1:
        return None

    remainder = line[opened + 1 :]
    tail = remainder.strip()
    if tail == "" or tail.startswith("#"):
        # The array opens on this line and its entries are on the ones below, so the new
        # entry becomes one of them, indented the way the first of them already is.
        following = lines[index + 1] if index + 1 < len(lines) else ""
        indent = following[: len(following) - len(following.lstrip(" \t"))] or "    "
        lines.insert(index + 1, f"{indent}{entry},{_terminator(line)}")
    else:
        separator = "" if tail.startswith("]") else ", "
        lines[index] = f"{line[: opened + 1]}{entry}{separator}{remainder}"
    return "".join(lines)


def _with_table_entries(
    text: str, table: str, entries: Sequence[str], declared: object
) -> str | None:
    """Insert *entries* into *table*, appending the table where the manifest declares none."""

    lines = text.splitlines(keepends=True)
    index = _header_index(lines, table)
    if index is not None:
        terminator = _terminator(lines[index])
        lines[index + 1 : index + 1] = [f"{entry}{terminator}" for entry in entries]
        return "".join(lines)
    if declared is not None:
        # The table is declared some other way, as a dotted key or an inline table, so a
        # header appended here would define it twice and the manifest would stop parsing.
        return None

    terminator = "\r\n" if "\r\n" in text else "\n"
    block = terminator.join(("", f"[{table}]", *entries, ""))
    return (text if text.endswith(terminator) else text + terminator) + block


def _header_index(lines: Sequence[str], table: str) -> int | None:
    """Return the index of the line declaring *table* as a header of its own."""

    pattern = re.compile(rf"^[ \t]*\[{re.escape(table)}\][ \t]*(?:#.*)?$")
    return next(
        (index for index, line in enumerate(lines) if pattern.match(line.rstrip("\r\n"))),
        None,
    )


def _table_end(lines: Sequence[str], header: int) -> int:
    """Return the index just past the last key the table opened at *header* holds.

    A key inserted there joins the table it belongs to rather than displacing the first
    key already written in it, and the blank line before the next header stays blank.
    """

    end = header + 1
    for index in range(header + 1, len(lines)):
        if _TABLE_HEADER.match(lines[index]):
            break
        if lines[index].strip():
            end = index + 1
    return end


def _key_index(lines: Sequence[str], header: int, key: str) -> int | None:
    """Return the index of *key* within the table opened at *header*.

    The search stops at the next header so that a key of the same name in another table,
    which is a different setting entirely, is never edited in its place.
    """

    pattern = re.compile(rf"^[ \t]*{re.escape(key)}[ \t]*=")
    for index in range(header + 1, len(lines)):
        if _TABLE_HEADER.match(lines[index]):
            return None
        if pattern.match(lines[index]):
            return index
    return None


def _describe_edits(
    requirement: str | None, scripts: Mapping[str, str], *, add_tools: bool
) -> tuple[str, ...]:
    """Say in plain English what was added to the manifest."""

    described: list[str] = []
    if requirement is not None:
        described.append(f"declared {requirement} under [project] dependencies")
    if scripts:
        named = " and ".join(f"'{key}'" for key in scripts)
        described.append(f"added the {named} script entries under [project.scripts]")
    if add_tools:
        described.append(f"added {', '.join(_DEVELOPMENT_TOOLS)} to the 'dev' dependency group")
    return tuple(described)


def _manual_edit_message(
    path: Path, requirement: str | None, scripts: Mapping[str, str], *, add_tools: bool
) -> str:
    """Name the entries a manifest this command cannot edit safely still needs."""

    pending: list[str] = []
    if requirement is not None:
        pending.append(f"{requirement} under [project] dependencies")
    pending.extend(f'{key} = "{value}" under [project.scripts]' for key, value in scripts.items())
    if add_tools:
        pending.append(f"{', '.join(_DEVELOPMENT_TOOLS)} in the 'dev' dependency group")
    return (
        f"{path} is not shaped in a way this command can edit without changing what the "
        "rest of the file means, so it was left alone. Add these by hand, then re-run "
        "'bustan init':\n" + "\n".join(f"  {entry}" for entry in pending)
    )


def _table_of(data: Mapping[str, Any], key: str) -> dict[str, Any]:
    """Return the table under *key*, or an empty one where the data holds no table there."""

    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _terminator(line: str) -> str:
    """Return the line ending *line* carries, so an inserted line matches the file's own."""

    return "\r\n" if line.endswith("\r\n") else "\n"


def _names_distribution(requirement: object, distribution: str) -> bool:
    """Report whether a requirement string names *distribution*."""

    if not isinstance(requirement, str):
        return False
    match = _REQUIREMENT_NAME.match(requirement.strip())
    if match is None:
        return False
    return _normalize_name(match.group()) == _normalize_name(distribution)


def _normalize_name(name: str) -> str:
    """Fold a distribution name the way an installer folds it before comparing."""

    return _NAME_SEPARATORS.sub("-", name.lower())


def _to_package_name(project_name: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_]+", "_", project_name.strip().lower()).strip("_")
    if not sanitized:
        return "bustan_app"
    if sanitized[0].isdigit():
        return f"app_{sanitized}"
    return sanitized
