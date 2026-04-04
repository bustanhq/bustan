"""Unit tests for repository Markdown link validation."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType


def test_slugify_heading_generates_github_like_anchors() -> None:
    checker = _load_checker_module()

    assert checker.slugify_heading("Open Source Project Docs") == "open-source-project-docs"
    assert checker.slugify_heading("Use `star.testing` safely") == "use-startesting-safely"


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


def _load_checker_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "check_markdown_links.py"
    module_spec = spec_from_file_location("check_markdown_links", script_path)
    assert module_spec is not None
    assert module_spec.loader is not None

    module = module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module