"""Unit tests for the API reference generator."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

import pytest


def test_render_api_reference_covers_the_stable_modules() -> None:
    generator = _load_generator_module()

    rendered_reference = generator.render_api_reference()

    assert "# API Reference" in rendered_reference
    assert "## `bustan`" in rendered_reference
    assert "#### `create_app`" in rendered_reference
    assert "## `bustan.testing`" in rendered_reference
    assert "#### `override_provider`" in rendered_reference
    assert "## `bustan.errors`" in rendered_reference
    assert "#### `ProviderResolutionError`" in rendered_reference


def test_render_api_reference_keeps_version_docs_stable_across_releases() -> None:
    generator = _load_generator_module()

    rendered_reference = generator.render_api_reference()

    assert "Installed distribution version string for the bustan package." in rendered_reference
    assert "Runtime behavior: resolved from the installed distribution metadata" in rendered_reference
    assert "Current value: `0.0.1`" not in rendered_reference


def test_check_api_reference_succeeds_when_reference_is_current(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    generator = _load_generator_module()
    output_path = tmp_path / "API_REFERENCE.md"
    output_path.write_text(generator.render_api_reference(), encoding="utf-8")

    exit_code = generator.check_api_reference(output_path)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert str(output_path) in captured.out
    assert "up to date" in captured.out


def test_check_api_reference_fails_when_reference_is_stale(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    generator = _load_generator_module()
    output_path = tmp_path / "API_REFERENCE.md"
    output_path.write_text("# stale\n", encoding="utf-8")

    exit_code = generator.check_api_reference(output_path)

    captured = capsys.readouterr()
    assert exit_code == 1
    assert str(output_path) in captured.out
    assert "out of sync" in captured.out
    assert "uv run python scripts/generate_api_reference.py" in captured.out


def _load_generator_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "generate_api_reference.py"
    module_spec = spec_from_file_location("generate_api_reference", script_path)
    assert module_spec is not None
    assert module_spec.loader is not None

    module = module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module