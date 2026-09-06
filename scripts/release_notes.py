"""Print the changelog section for one version, for a release body."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
# A release heading, whether or not its version is a link: "## [2.0.0-rc.2](...) (date)".
RELEASE_HEADING_RE = re.compile(r"^##\s+(?:\[(?P<linked>[^\]]+)\]\([^)]*\)|(?P<plain>\S+))")


def main(argv: list[str]) -> int:
    """Print the notes for the version named on the command line."""

    if len(argv) != 1:
        print("usage: release_notes.py <version>", file=sys.stderr)
        return 2

    notes = extract_notes(CHANGELOG.read_text(encoding="utf-8"), argv[0])
    if notes is None:
        # The publish workflow reads this, so a version with no entry has to stop the
        # release rather than publish an empty body: the notes are the release.
        print(f"{CHANGELOG.name} has no section for version {argv[0]}", file=sys.stderr)
        return 1

    print(notes)
    return 0


def extract_notes(changelog: str, version: str) -> str | None:
    """Return the body under the heading for a version, or None when there is none."""

    wanted = normalize(version)
    lines = changelog.splitlines()
    collected: list[str] | None = None
    for line in lines:
        match = RELEASE_HEADING_RE.match(line)
        if match is None:
            if collected is not None:
                collected.append(line)
            continue
        if collected is not None:
            break
        heading = match.group("linked") or match.group("plain")
        if normalize(heading) == wanted:
            collected = []

    if collected is None:
        return None
    return "\n".join(collected).strip()


def normalize(version: str) -> str:
    """Return a version with the spellings of a pre-release made comparable.

    A tag, a package version and a changelog heading disagree about punctuation for
    the same release: `2.0.0rc2`, `2.0.0-rc.2`, `v2.0.0-rc.2`. Only the characters
    carry meaning here, so the separators are dropped rather than guessed at.
    """

    return version.removeprefix("v").replace("-", "").replace(".", "").replace("_", "").lower()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
