"""Unit tests for repository Markdown link validation."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

import pytest


def test_slugify_heading_generates_github_like_anchors() -> None:
    checker = _load_checker_module()

    assert checker.slugify_heading("Open Source Project Docs") == "open-source-project-docs"
    assert checker.slugify_heading("Use `bustan.testing` safely") == "use-bustantesting-safely"


def test_check_markdown_links_accepts_valid_relative_links(tmp_path: Path) -> None:
    checker = _load_checker_module()
    docs_directory = tmp_path / "docs"
    docs_directory.mkdir()

    index_path = docs_directory / "index.md"
    guide_path = docs_directory / "guide.md"
    index_path.write_text("# Index\n\nSee [Guide](guide.md#getting-started).\n", encoding="utf-8")
    guide_path.write_text("# Guide\n\n## Getting Started\n", encoding="utf-8")

    errors = checker.check_markdown_links([index_path, guide_path])

    assert errors == []


def test_check_markdown_links_reports_missing_file_or_anchor(tmp_path: Path) -> None:
    checker = _load_checker_module()

    readme_path = tmp_path / "README.md"
    readme_path.write_text(
        "# README\n\n[Missing](missing.md)\n[Bad Anchor](README.md#nope)\n",
        encoding="utf-8",
    )

    errors = checker.check_markdown_links([readme_path])

    assert len(errors) == 2
    assert any("missing target file" in error for error in errors)
    assert any("missing target anchor" in error for error in errors)


def test_check_markdown_links_accepts_self_referential_blob_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checker = _load_checker_module()
    monkeypatch.setattr(checker, "REPO_ROOT", tmp_path)
    _write_pyproject(tmp_path, "2.0.0")
    docs_directory = tmp_path / "docs"
    docs_directory.mkdir()

    readme_path = tmp_path / "README.md"
    docs_index_path = docs_directory / "README.md"
    readme_path.write_text(
        "# README\n\nSee [Tutorials]"
        "(https://github.com/bustanhq/bustan/blob/v2.0.0/docs/README.md#tutorials).\n",
        encoding="utf-8",
    )
    docs_index_path.write_text("# Documentation\n\n## Tutorials\n", encoding="utf-8")

    errors = checker.check_markdown_links([readme_path, docs_index_path])

    assert errors == []


def test_check_markdown_links_reports_missing_blob_url_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checker = _load_checker_module()
    monkeypatch.setattr(checker, "REPO_ROOT", tmp_path)
    _write_pyproject(tmp_path, "2.0.0")

    readme_path = tmp_path / "README.md"
    readme_path.write_text(
        "# README\n\n[Stability]"
        "(https://github.com/bustanhq/bustan/blob/v2.0.0/docs/reference/stability.md)\n",
        encoding="utf-8",
    )

    errors = checker.check_markdown_links([readme_path])

    assert len(errors) == 1
    assert "missing target file" in errors[0]


def test_check_markdown_links_reports_missing_blob_url_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checker = _load_checker_module()
    monkeypatch.setattr(checker, "REPO_ROOT", tmp_path)
    _write_pyproject(tmp_path, "2.0.0")
    docs_directory = tmp_path / "docs"
    docs_directory.mkdir()

    readme_path = tmp_path / "README.md"
    docs_index_path = docs_directory / "README.md"
    readme_path.write_text(
        "# README\n\n[How-to guides]"
        "(https://github.com/bustanhq/bustan/blob/v2.0.0/docs/README.md#how-to-guide)\n",
        encoding="utf-8",
    )
    docs_index_path.write_text("# Documentation\n\n## How-to guides\n", encoding="utf-8")

    errors = checker.check_markdown_links([readme_path, docs_index_path])

    assert len(errors) == 1
    assert "missing target anchor" in errors[0]


def test_check_markdown_links_skips_urls_naming_another_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checker = _load_checker_module()
    monkeypatch.setattr(checker, "REPO_ROOT", tmp_path)

    readme_path = tmp_path / "README.md"
    readme_path.write_text(
        "# README\n\n[uv](https://docs.astral.sh/uv/)\n"
        "[Elsewhere](https://github.com/other/repo/blob/v2.0.0/docs/absent.md#absent)\n",
        encoding="utf-8",
    )

    errors = checker.check_markdown_links([readme_path])

    assert errors == []


def test_check_markdown_links_checks_a_blob_url_carrying_a_title(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checker = _load_checker_module()
    monkeypatch.setattr(checker, "REPO_ROOT", tmp_path)
    _write_pyproject(tmp_path, "2.0.0")

    readme_path = tmp_path / "README.md"
    readme_path.write_text(
        "# README\n\n[Licence]"
        '(https://github.com/bustanhq/bustan/blob/v2.0.0/LICENCE "The licence")\n',
        encoding="utf-8",
    )

    errors = checker.check_markdown_links([readme_path])

    assert len(errors) == 1
    assert "missing target file" in errors[0]


def test_check_markdown_links_checks_the_link_around_a_badge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checker = _load_checker_module()
    monkeypatch.setattr(checker, "REPO_ROOT", tmp_path)
    _write_pyproject(tmp_path, "2.0.0")

    readme_path = tmp_path / "README.md"
    readme_path.write_text(
        "# README\n\n[![Licence](https://img.shields.io/badge/licence-MIT-blue.svg)]"
        "(https://github.com/bustanhq/bustan/blob/v2.0.0/LICENCE)\n",
        encoding="utf-8",
    )

    errors = checker.check_markdown_links([readme_path])

    assert errors == [
        "README.md:3: missing target file: https://github.com/bustanhq/bustan/blob/v2.0.0/LICENCE"
    ]


def test_check_markdown_links_reports_a_readme_ref_that_is_not_the_packaged_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checker = _load_checker_module()
    monkeypatch.setattr(checker, "REPO_ROOT", tmp_path)
    _write_pyproject(tmp_path, "2.0.1")
    (tmp_path / "LICENSE").write_text("MIT\n", encoding="utf-8")

    readme_path = tmp_path / "README.md"
    readme_path.write_text(
        "# README\n\n[MIT](https://github.com/bustanhq/bustan/blob/v2.0.0/LICENSE)\n",
        encoding="utf-8",
    )

    errors = checker.check_markdown_links([readme_path])

    assert errors == [
        "README.md:3: ref v2.0.0 is not v2.0.1, the version pyproject.toml packages: "
        "https://github.com/bustanhq/bustan/blob/v2.0.0/LICENSE"
    ]


def test_check_markdown_links_checks_raw_urls_in_html_image_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checker = _load_checker_module()
    monkeypatch.setattr(checker, "REPO_ROOT", tmp_path)
    _write_pyproject(tmp_path, "2.0.1")
    assets_directory = tmp_path / "docs" / "assets"
    assets_directory.mkdir(parents=True)
    (assets_directory / "wordmark.svg").write_text("<svg/>\n", encoding="utf-8")

    raw = "https://raw.githubusercontent.com/bustanhq/bustan"
    readme_path = tmp_path / "README.md"
    readme_path.write_text(
        "<picture>\n"
        f'  <source srcset="{raw}/v2.0.1/docs/assets/wordmark-dark.svg">\n'
        f'  <img src="{raw}/v2.0.1/docs/assets/wordmark.svg" alt="Bustan">\n'
        "</picture>\n"
        f'<img src="{raw}/v2.0.0/docs/assets/wordmark.svg" alt="Bustan">\n',
        encoding="utf-8",
    )

    errors = checker.check_markdown_links([readme_path])

    assert errors == [
        f"README.md:2: missing target file: {raw}/v2.0.1/docs/assets/wordmark-dark.svg",
        "README.md:5: ref v2.0.0 is not v2.0.1, the version pyproject.toml packages: "
        f"{raw}/v2.0.0/docs/assets/wordmark.svg",
    ]


def test_check_markdown_links_leaves_other_documents_free_to_pin_any_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checker = _load_checker_module()
    monkeypatch.setattr(checker, "REPO_ROOT", tmp_path)
    _write_pyproject(tmp_path, "2.0.1")
    (tmp_path / "LICENSE").write_text("MIT\n", encoding="utf-8")
    docs_directory = tmp_path / "docs"
    docs_directory.mkdir()

    docs_index_path = docs_directory / "README.md"
    docs_index_path.write_text(
        "# Documentation\n\n[Licence at 1.1.0]"
        "(https://github.com/bustanhq/bustan/blob/v1.1.0/LICENSE)\n",
        encoding="utf-8",
    )

    errors = checker.check_markdown_links([docs_index_path])

    assert errors == []


def test_iter_markdown_files_excludes_work_backlog_files(tmp_path: Path) -> None:
    checker = _load_checker_module()

    docs_directory = tmp_path / "docs"
    docs_directory.mkdir()
    work_directory = tmp_path / "work"
    work_directory.mkdir()

    docs_file = docs_directory / "guide.md"
    work_file = work_directory / "ticket-000.md"
    docs_file.write_text("# Guide\n", encoding="utf-8")
    work_file.write_text("# Ticket\n", encoding="utf-8")

    assert checker.iter_markdown_files(tmp_path) == [docs_file]


def _write_pyproject(root: Path, version: str) -> None:
    (root / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n', encoding="utf-8")


def _load_checker_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "check_markdown_links.py"
    module_spec = spec_from_file_location("check_markdown_links", script_path)
    assert module_spec is not None
    assert module_spec.loader is not None

    module = module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module
