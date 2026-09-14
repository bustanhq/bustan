"""Validate repository-local Markdown links and heading anchors."""

from __future__ import annotations

import re
import tomllib
from collections import Counter
from functools import cache
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
# A badge is an image inside a link, `[![alt](image)](target)`. Link text ends at the
# image's own `]`, which would take the image's source for the link's target, so every
# image is replaced before links are read; an image is not a link, and is not checked.
# Nesting the image pattern inside the link pattern instead backtracks exponentially.
IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
# An HTML image names its URL in a `src` or `srcset` attribute, which no Markdown link
# syntax reaches. Only the first candidate of a `srcset` is read.
HTML_SOURCE_RE = re.compile(r"\b(?:srcset|src)=\"\s*([^\"\s]+)")
# A README shipped to a package index is read on that index's host, so its links to
# repository documents are absolute. Those URLs address files in this repository, so they
# are checked like relative targets: the path is resolved from the repository root and the
# anchor validated against the target file's headings. A raw URL addresses the same file as
# the blob URL with its ref and path, and is checked the same way.
#
# The ref is never resolved. `actions/checkout@v7` fetches neither tags nor history, so a
# CI checkout cannot resolve `v2.0.0` and a check that tried would pass locally and fail
# there. The path and the anchor are validated against the working tree.
#
# The README's refs are still read. The package index renders that file from the
# distribution a release uploads, so each of its URLs must name the tag the release is cut
# from: `v` followed by the version pyproject.toml packages, the only tag the publish
# workflow accepts for that version. Any other document may pin any ref, a historical tag
# included.
#
# A trailing link title is tolerated and ignored, as normalize_target does for a relative
# target: a URL the pattern does not match is skipped, and a skip is what this check exists
# to avoid.
REPO_URL_RE = re.compile(
    r"^https://(?:github\.com/bustanhq/bustan/blob|raw\.githubusercontent\.com/bustanhq/bustan)"
    r"/([^/\s]+)/(\S+?)(?:\s+\S.*)?$"
)


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
    if not normalized_target:
        return None

    if normalized_target.startswith("#"):
        anchor = normalized_target[1:]
        if anchor and anchor not in anchor_cache[source_file]:
            return format_error(source_file, line_number, target, "missing in-file anchor")
        return None

    base_directory = source_file.parent
    repo_url = repo_url_target(normalized_target)
    if repo_url is not None:
        ref, normalized_target = repo_url
        ref_error = readme_ref_error(source_file, ref)
        if ref_error is not None:
            return format_error(source_file, line_number, target, ref_error)
        base_directory = REPO_ROOT
    elif normalized_target.startswith(("http://", "https://", "mailto:")):
        return None

    path_part, separator, fragment = normalized_target.partition("#")
    resolved_path = (base_directory / unquote(path_part)).resolve()
    if not resolved_path.exists():
        return format_error(source_file, line_number, target, "missing target file")

    if (
        separator
        and resolved_path in markdown_files
        and fragment not in anchor_cache[resolved_path]
    ):
        return format_error(source_file, line_number, target, "missing target anchor")

    return None


def repo_url_target(target: str) -> tuple[str, str] | None:
    """Return the ref and the repository-root-relative target a self-referential URL names.

    A URL naming another host, another repository, or this repository without a path
    below the ref is not repo-local, and returns None so the caller skips it.
    """

    match = REPO_URL_RE.match(target)
    if match is None:
        return None

    ref, repo_target = match.group(1), match.group(2)
    return None if repo_target.startswith("#") else (ref, repo_target)


def readme_ref_error(source_file: Path, ref: str) -> str | None:
    """Return why a self-referential URL's ref cannot stand in source_file, or None if it can.

    Only the repository's README is held to a ref: the tag of the version pyproject.toml
    packages.
    """

    if source_file != REPO_ROOT / "README.md":
        return None

    packaged_ref = f"v{packaged_version(REPO_ROOT)}"
    if ref == packaged_ref:
        return None
    return f"ref {ref} is not {packaged_ref}, the version pyproject.toml packages"


@cache
def packaged_version(repo_root: Path) -> str:
    """Return the version the pyproject.toml under repo_root packages."""

    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    return str(pyproject["project"]["version"])


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
    """Extract raw Markdown link targets and HTML image source URLs from one line."""

    links = LINK_RE.finditer(IMAGE_RE.sub("image", line))
    targets = [match.group(1).strip() for match in links]
    targets.extend(match.group(1) for match in HTML_SOURCE_RE.finditer(line))
    return targets


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
