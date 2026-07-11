"""Validate repository-local Markdown links and heading anchors."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRECTORIES = {
    ".draft",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "work",
}
FENCE_RE = re.compile(r"^(```|~~~)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def main() -> int:
    """Check Markdown files under the repository root."""

    markdown_files = tuple(iter_markdown_files(REPO_ROOT))
    errors = check_markdown_links(markdown_files)
    if errors:
        for error in errors:
            print(error)
        return 1

    print(f"Checked {len(markdown_files)} Markdown files with no link errors.")
    return 0


def iter_markdown_files(root: Path) -> list[Path]:
    """Return Markdown files under root, excluding generated and draft directories."""

    markdown_files: list[Path] = []
    for path in root.rglob("*.md"):
        if any(part in EXCLUDED_DIRECTORIES for part in path.parts):
            continue
        markdown_files.append(path)
    return sorted(markdown_files)


def check_markdown_links(markdown_files: tuple[Path, ...] | list[Path]) -> list[str]:
    """Return a list of validation errors for repo-local Markdown links."""

    anchor_cache = {
        markdown_file: collect_heading_anchors(markdown_file) for markdown_file in markdown_files
    }
    markdown_file_set = set(markdown_files)
    errors: list[str] = []

    for markdown_file in markdown_files:
        content = markdown_file.read_text(encoding="utf-8")
        for line_number, line in enumerate(strip_fenced_code_blocks(content).splitlines(), start=1):
            for target in extract_markdown_targets(line):
                link_error = validate_markdown_target(
                    markdown_file,
                    line_number,
                    target,
                    markdown_file_set,
                    anchor_cache,
                )
                if link_error is not None:
                    errors.append(link_error)

    return errors


def validate_markdown_target(
    source_file: Path,
    line_number: int,
    target: str,
    markdown_files: set[Path],
    anchor_cache: dict[Path, set[str]],
) -> str | None:
    """Validate one Markdown link target and return an error string if invalid."""

    normalized_target = normalize_target(target)
    if not normalized_target or normalized_target.startswith(("http://", "https://", "mailto:")):
        return None

    if normalized_target.startswith("#"):
        anchor = normalized_target[1:]
        if anchor and anchor not in anchor_cache[source_file]:
            return format_error(source_file, line_number, target, "missing in-file anchor")
        return None

    path_part, separator, fragment = normalized_target.partition("#")
    resolved_path = (source_file.parent / unquote(path_part)).resolve()
    if not resolved_path.exists():
        return format_error(source_file, line_number, target, "missing target file")

    if (
        separator
        and resolved_path in markdown_files
        and fragment not in anchor_cache[resolved_path]
    ):
        return format_error(source_file, line_number, target, "missing target anchor")

    return None


def collect_heading_anchors(markdown_file: Path) -> set[str]:
    """Collect GitHub-style heading anchors from one Markdown file."""

    text = markdown_file.read_text(encoding="utf-8")
    anchors: set[str] = set()
    duplicates: Counter[str] = Counter()

    for line in strip_fenced_code_blocks(text).splitlines():
        match = HEADING_RE.match(line.strip())
        if match is None:
            continue

        base_anchor = slugify_heading(match.group(2))
        if not base_anchor:
            continue

        anchor_index = duplicates[base_anchor]
        duplicates[base_anchor] += 1
        anchor = base_anchor if anchor_index == 0 else f"{base_anchor}-{anchor_index}"
        anchors.add(anchor)

    return anchors


def strip_fenced_code_blocks(text: str) -> str:
    """Remove fenced code-block contents from Markdown before link scanning."""

    stripped_lines: list[str] = []
    in_fence = False
    fence_marker = ""

    for line in text.splitlines():
        fence_match = FENCE_RE.match(line.strip())
        if fence_match is not None:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = ""
            stripped_lines.append("")
            continue

        stripped_lines.append("" if in_fence else line)

    return "\n".join(stripped_lines)


def extract_markdown_targets(line: str) -> list[str]:
    """Extract raw Markdown link targets from one line."""

    return [match.group(1).strip() for match in LINK_RE.finditer(line)]


def normalize_target(target: str) -> str:
    """Normalize a Markdown target by stripping wrappers and optional titles."""

    normalized_target = target.strip()
    if normalized_target.startswith("<") and normalized_target.endswith(">"):
        normalized_target = normalized_target[1:-1].strip()

    if normalized_target.startswith(("http://", "https://", "mailto:")):
        return normalized_target

    if ' "' in normalized_target:
        normalized_target = normalized_target.split(' "', maxsplit=1)[0]
    if " '" in normalized_target:
        normalized_target = normalized_target.split(" '", maxsplit=1)[0]

    return normalized_target


def slugify_heading(heading: str) -> str:
    """Return a GitHub-like anchor slug for a Markdown heading."""

    normalized_heading = re.sub(r"`([^`]*)`", r"\1", heading.strip().lower())
    normalized_heading = re.sub(r"\[[^\]]+\]\([^)]+\)", "", normalized_heading)
    normalized_heading = re.sub(r"[^a-z0-9\s-]", "", normalized_heading)
    normalized_heading = re.sub(r"\s+", "-", normalized_heading.strip())
    normalized_heading = re.sub(r"-+", "-", normalized_heading)
    return normalized_heading


def format_error(source_file: Path, line_number: int, target: str, reason: str) -> str:
    """Format one Markdown link validation error."""

    relative_path = (
        source_file
        if not source_file.is_relative_to(REPO_ROOT)
        else source_file.relative_to(REPO_ROOT)
    )
    return f"{relative_path}:{line_number}: {reason}: {target}"


if __name__ == "__main__":
    raise SystemExit(main())
