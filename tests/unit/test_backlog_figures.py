"""Unit tests keeping the delivery backlog from stating counts the tree can move.

The backlog is the one document every delivery agent reads before its own ticket, so a
count written into it is written into every checkout at once, and it goes wrong
quietly: the agent's own tree stays right, and the only agents a stale count costs are
the ones that trusted the document over the tree. The document therefore states no
count a reader could have measured, and points at the tree instead. That rule is
asserted here because a rule nothing checks is the same defect one edit later.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKLOG_PATH = REPO_ROOT / "docs" / "delivery" / "BUSTAN_2_0_BACKLOG.md"

BRIEF_HEADING = "## Shared context brief"

# Shapes of count that describe the tree and therefore decay as the tree grows. These
# are the ones the backlog has actually carried; a new shape is added here when the
# document starts carrying it, not before. The lookbehind keeps a ticket id such as
# T-003 from reading as the count 003.
_COUNT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![\w-])\d[\d,]*(?:\s+\w+)?\s+tests?\b"),
    re.compile(r"(?<![\w-])\d[\d,]*-element\b"),
    re.compile(r"(?<![\w-])\d[\d,]*(?:\s+\w+)?\s+lines\b"),
    re.compile(r"(?<![\w-])\d[\d,]*-line\b"),
    re.compile(r"(?<![\w-])\d[\d,]*(?:\s+\w+)?\s+examples?\b"),
)

# A count may stand in the backlog only by being named here with the reason the tree
# cannot move it. An entry is a decision on the record; without one, a count that
# reappears is indistinguishable from the stale counts this guard exists to stop.
PERMITTED_COUNTS: dict[str, str] = {
    "roughly 50 lines": (
        "A ceiling the standards put on new code rather than a measurement of the "
        "code that exists, so no merge can make it untrue."
    ),
    "931-line file": (
        "The size the audit measured of the resolver that wave 1 replaced. It is "
        "pinned to a file the tree no longer has, so it reads as history and cannot "
        "be mistaken for a fact about the current tree."
    ),
}

# A backtick-quoted token counts as a path when it has no spaces and either contains a
# directory separator or ends in an extension the repository uses. That leaves module
# and symbol names such as bustan.errors alone, which are checked by the public surface
# tests rather than by looking for a file.
_PATH_SUFFIXES = (".py", ".md", ".toml", ".yml", ".yaml", ".json", ".cfg", ".txt")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_FENCED_BLOCK_RE = re.compile(r"```[a-z]*\n(.*?)```", re.DOTALL)
_PATH_TOKEN_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")


def _backlog_text() -> str:
    return BACKLOG_PATH.read_text(encoding="utf-8")


def _brief_section(text: str) -> str:
    """Return the shared context brief, the part of the backlog read as current fact."""

    heading = re.search(rf"^{re.escape(BRIEF_HEADING)}$", text, re.MULTILINE)
    assert heading is not None, (
        f"docs/delivery/BUSTAN_2_0_BACKLOG.md has no '{BRIEF_HEADING}' heading. The "
        "brief is the section every agent reads as current fact, so this guard has "
        "nothing to check until the heading is restored or this constant is updated."
    )
    end = text.find("\n## ", heading.end())
    return text[heading.start() :] if end == -1 else text[heading.start() : end]


def _looks_like_a_path(token: str) -> bool:
    candidate = token.rstrip("/")
    if not _PATH_TOKEN_RE.match(candidate):
        return False
    return "/" in candidate or candidate.endswith(_PATH_SUFFIXES)


def _paths_named_in_prose(section: str) -> set[str]:
    return {
        token.rstrip("/") for token in _INLINE_CODE_RE.findall(section) if _looks_like_a_path(token)
    }


def _paths_named_in_commands(section: str) -> set[str]:
    return {
        token
        for block in _FENCED_BLOCK_RE.findall(section)
        for token in block.split()
        if "/" in token and token.endswith(_PATH_SUFFIXES) and _looks_like_a_path(token)
    }


def _permitted_spans(text: str) -> list[tuple[int, int]]:
    """Return the character ranges of every permitted count, so matches inside them pass."""

    spans = []
    for phrase in PERMITTED_COUNTS:
        start = text.find(phrase)
        while start != -1:
            spans.append((start, start + len(phrase)))
            start = text.find(phrase, start + 1)
    return spans


def _stated_counts() -> list[str]:
    text = _backlog_text()
    permitted = _permitted_spans(text)
    stated = []
    for pattern in _COUNT_PATTERNS:
        for match in pattern.finditer(text):
            inside = any(start <= match.start() and match.end() <= end for start, end in permitted)
            if not inside:
                line = text.count("\n", 0, match.start()) + 1
                stated.append(f"line {line}: {match.group(0)!r}")
    return sorted(stated)


def test_the_backlog_states_no_count_the_tree_can_move() -> None:
    stated = _stated_counts()

    assert not stated, (
        "docs/delivery/BUSTAN_2_0_BACKLOG.md states a count of the tree at "
        f"{'; '.join(stated)}. Say where the number is read from instead, so the "
        "reader measures it in their own checkout, or add the exact phrase to "
        "PERMITTED_COUNTS with the reason the tree cannot move it."
    )


def test_every_permitted_count_still_appears_in_the_backlog() -> None:
    text = _backlog_text()
    absent = sorted(phrase for phrase in PERMITTED_COUNTS if phrase not in text)

    assert not absent, (
        f"PERMITTED_COUNTS excuses {', '.join(repr(phrase) for phrase in absent)}, "
        "which the backlog no longer contains, so the exclusion permits nothing and "
        "is stale. Delete the entry."
    )


def test_every_permitted_count_states_a_reason() -> None:
    unexplained = sorted(
        phrase for phrase, reason in PERMITTED_COUNTS.items() if not reason.strip()
    )

    assert not unexplained, (
        f"PERMITTED_COUNTS lists {', '.join(repr(phrase) for phrase in unexplained)} "
        "with no reason. An omission without one is indistinguishable from an oversight."
    )


def test_every_path_the_brief_names_in_prose_exists() -> None:
    named = _paths_named_in_prose(_brief_section(_backlog_text()))
    missing = sorted(path for path in named if not (REPO_ROOT / path).exists())

    assert named, (
        "No repository path was found in the shared context brief, so this guard is inert."
    )
    assert not missing, (
        f"The shared context brief sends the reader to {', '.join(missing)}, which the "
        "repository does not have. A figure the brief tells the reader to measure is "
        "only as good as the path it names, so update the brief or restore the path."
    )


def test_every_path_the_briefs_commands_name_exists() -> None:
    named = _paths_named_in_commands(_brief_section(_backlog_text()))
    missing = sorted(path for path in named if not (REPO_ROOT / path).exists())

    assert named, "No script path was found in the brief's commands, so this guard is inert."
    assert not missing, (
        f"The verification block in the shared context brief runs {', '.join(missing)}, "
        "which the repository does not have. Every agent is told to run that block "
        "before requesting review, so a missing script fails all of them at once."
    )


def test_the_brief_points_at_this_guard() -> None:
    own_path = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()
    brief = _brief_section(_backlog_text())

    assert own_path in brief, (
        f"The shared context brief does not name {own_path}, so a reader who adds a "
        "count back to the backlog has no way to know what will reject it. Name this "
        "file in the brief, or rename this file to the one the brief names."
    )
