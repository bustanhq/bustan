"""Unit tests for the release-notes extractor the publish workflow reads."""

from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

CHANGELOG = """# Changelog

## [2.0.0-rc.2](https://github.com/o/r/compare/v1.1.0...v2.0.0rc2) (2026-09-06)

The notes for the release being cut.

### Correctness

* something was fixed ([#1](https://github.com/o/r/issues/1))

## [1.1.0](https://github.com/o/r/compare/v1.0.1...v1.1.0) (2026-05-07)

The previous release, which must not appear in the notes above.
"""


def test_the_notes_are_the_section_under_the_matching_heading() -> None:
    notes = _load_module().extract_notes(CHANGELOG, "2.0.0rc2")

    assert notes is not None
    assert notes.startswith("The notes for the release being cut.")
    assert "something was fixed" in notes
    assert "must not appear" not in notes


def test_a_tag_a_package_version_and_a_heading_name_the_same_release() -> None:
    module = _load_module()

    spellings = ("v2.0.0-rc.2", "2.0.0-rc.2", "2.0.0rc2")

    assert {module.extract_notes(CHANGELOG, spelling) for spelling in spellings} == {
        module.extract_notes(CHANGELOG, "2.0.0-rc.2")
    }


def test_a_version_with_no_section_is_reported_rather_than_guessed_at() -> None:
    assert _load_module().extract_notes(CHANGELOG, "9.9.9") is None


def test_the_last_section_in_the_file_ends_at_the_end_of_the_file() -> None:
    notes = _load_module().extract_notes(CHANGELOG, "1.1.0")

    assert notes == "The previous release, which must not appear in the notes above."


def test_the_repository_changelog_has_notes_for_the_packaged_version() -> None:
    import tomllib

    repository_root = Path(__file__).resolve().parents[2]
    version = tomllib.loads((repository_root / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]

    notes = _load_module().extract_notes(
        (repository_root / "CHANGELOG.md").read_text(encoding="utf-8"), version
    )

    assert notes, f"CHANGELOG.md has no section for the packaged version {version}"


def _load_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "release_notes.py"
    module_spec = spec_from_file_location("release_notes", script_path)
    assert module_spec is not None
    assert module_spec.loader is not None

    module = module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module
