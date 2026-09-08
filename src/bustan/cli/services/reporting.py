"""Rendering of a command's report as an aligned table or as JSON.

A diagnostic command answers two readers at once: a person at a terminal, who wants
columns lined up, and a script, which wants the same data as JSON it can parse. Both
are rendered from one description of the report, so the two can never drift into
disagreeing about what the command found.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

TABLE_FORMAT = "table"
JSON_FORMAT = "json"
OUTPUT_FORMATS: tuple[str, ...] = (TABLE_FORMAT, JSON_FORMAT)

# What a cell holds when its value is absent or empty. A blank cell in an aligned table
# is indistinguishable from a column that ran out of rows, so an empty value is spelled.
_EMPTY_CELL = "-"
_COLUMN_SEPARATOR = "  "
_EMPTY_SECTION = "(none)"


@dataclass(frozen=True, slots=True)
class ReportSection:
    """One titled block of rows: a table under the table format, a key under JSON.

    ``columns`` names the row keys to render, in the order a reader should see them.
    The JSON form carries whole rows rather than the named columns, because a script
    reading it should not lose a field that the terminal had no room for.
    """

    key: str
    title: str
    columns: tuple[str, ...]
    rows: tuple[Mapping[str, object], ...]


def add_format_option(parser: argparse.ArgumentParser) -> None:
    """Give a subcommand the shared ``--format`` option."""

    parser.add_argument(
        "--format",
        dest="output_format",
        choices=OUTPUT_FORMATS,
        default=TABLE_FORMAT,
        help="Render the report as an aligned table or as JSON (default: table).",
    )


def render_report(sections: Sequence[ReportSection], output_format: str) -> str:
    """Render *sections* in the requested format."""

    if output_format == JSON_FORMAT:
        return render_json(sections)
    return render_table(sections)


def render_json(sections: Sequence[ReportSection]) -> str:
    """Render *sections* as one JSON object keyed by section.

    ``default=str`` is the last resort for a value the framework did not produce: a
    configuration file can hold anything its loader returns, and a report that refuses
    to render is worse to an operator than one that renders a value as its text.
    """

    payload = {section.key: [dict(row) for row in section.rows] for section in sections}
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


def render_table(sections: Sequence[ReportSection]) -> str:
    """Render *sections* as titled tables with their columns aligned."""

    blocks = [_render_section(section) for section in sections]
    return "\n\n".join(blocks)


def _render_section(section: ReportSection) -> str:
    """Render one section: its title, then its rows under aligned headings."""

    heading = f"{section.title} ({len(section.rows)})"
    if not section.rows:
        return f"{heading}\n{_EMPTY_SECTION}"

    header = tuple(section.columns)
    cells = tuple(
        tuple(render_cell(row.get(column)) for column in section.columns) for row in section.rows
    )
    widths = _column_widths((header, *cells))
    lines = [
        _render_row(header, widths),
        _render_row(tuple("-" * width for width in widths), widths),
    ]
    lines.extend(_render_row(row, widths) for row in cells)
    return "\n".join([heading, *lines])


def _column_widths(rows: Sequence[Sequence[str]]) -> tuple[int, ...]:
    """Return the width each column needs to hold its widest cell.

    The heading row is one of the rows, so there is always at least one to measure.
    """

    return tuple(max(len(row[index]) for row in rows) for index in range(len(rows[0])))


def _render_row(cells: Sequence[str], widths: Sequence[int]) -> str:
    """Render one row, padding every cell but the last to its column's width."""

    padded = [cell.ljust(width) for cell, width in zip(cells[:-1], widths[:-1], strict=False)]
    padded.extend(cells[len(padded) :])
    return _COLUMN_SEPARATOR.join(padded).rstrip()


def render_cell(value: object) -> str:
    """Render one value as table text.

    Booleans read as yes and no rather than as their Python spelling, because a column
    of True and False is read as data the application set rather than as an answer to
    the question the heading asks.
    """

    if value is None:
        return _EMPTY_CELL
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list | tuple):
        return ", ".join(render_cell(item) for item in value) or _EMPTY_CELL
    return str(value) or _EMPTY_CELL
