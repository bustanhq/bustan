"""Unit tests keeping the troubleshooting guide in step with the error surface.

A reader who hits a framework refusal reads the class name out of the traceback and
searches for it. A class the guide never names sends that reader away with nothing,
and the drift is invisible to whoever added the class, so it is asserted here instead
of left to be discovered.
"""

from __future__ import annotations

import re
from pathlib import Path

import bustan.errors as bustan_errors

TROUBLESHOOTING_PATH = Path(__file__).resolve().parents[2] / "docs" / "TROUBLESHOOTING.md"

# A class may be left out of the guide only by naming it here with the reason a reader
# can never meet it, so that an omission is a decision on the record rather than a gap.
# It is empty because every exported class is reachable from ordinary application code.
UNDOCUMENTED_ERRORS: dict[str, str] = {}

_ENTRY_HEADING_RE = re.compile(r"^## `(?P<name>\w+)`$", re.MULTILINE)


def _entry_headings() -> set[str]:
    """Return every class name the guide gives a top-level entry to."""

    return {
        match.group("name")
        for match in _ENTRY_HEADING_RE.finditer(TROUBLESHOOTING_PATH.read_text(encoding="utf-8"))
    }


def test_every_exported_error_has_an_entry() -> None:
    documented = _entry_headings()
    missing = sorted(
        name
        for name in bustan_errors.__all__
        if name not in documented and name not in UNDOCUMENTED_ERRORS
    )

    assert not missing, (
        f"docs/TROUBLESHOOTING.md has no '## `<name>`' entry for {', '.join(missing)}. "
        "Add one keyed by the class name a reader reads out of the traceback, or list the "
        "class in UNDOCUMENTED_ERRORS with the reason it cannot be reached."
    )


def test_every_entry_names_an_exported_error() -> None:
    documented = _entry_headings()
    stale = sorted(name for name in documented if name not in bustan_errors.__all__)

    assert not stale, (
        f"docs/TROUBLESHOOTING.md keeps an entry for {', '.join(stale)}, which "
        "bustan.errors no longer exports. Remove the entry or restore the export."
    )


def test_no_exclusion_names_a_class_that_is_not_exported() -> None:
    unexported = sorted(name for name in UNDOCUMENTED_ERRORS if name not in bustan_errors.__all__)

    assert not unexported, (
        f"UNDOCUMENTED_ERRORS excuses {', '.join(unexported)} from the guide, but "
        "bustan.errors does not export it, so the exclusion hides nothing and is stale."
    )


def test_every_exclusion_states_a_reason() -> None:
    unexplained = sorted(name for name, reason in UNDOCUMENTED_ERRORS.items() if not reason.strip())

    assert not unexplained, (
        f"UNDOCUMENTED_ERRORS lists {', '.join(unexplained)} with no reason. An omission "
        "without one is indistinguishable from an oversight."
    )
