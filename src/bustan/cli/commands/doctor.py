"""The ``bustan doctor`` command: what 2.0 changed under a codebase, and the fix."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..services.failures import COMMAND_FAILURES, report_failure
from ..services.migrations import (
    ScanResult,
    finding_rows,
    scan_path,
    scan_summary,
    skipped_rows,
)
from ..services.reporting import (
    JSON_FORMAT,
    ReportSection,
    add_format_option,
    render_json,
)

# A scan fails when the caller still has work to do and when the scan proved nothing:
# a finding is an edit somebody has to make, and a tree where not one file could be
# parsed was never checked at all. Either way the command has to fail, which is what
# lets it stand in a migration's pipeline as well as in a terminal.
_FAILING_EXIT_CODE = 1


def register_doctor_command(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "doctor",
        help="Scan a codebase for constructs that 2.0 changed, and print the fix for each.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="File or directory to scan (default: the current directory).",
    )
    add_format_option(parser)


def run_doctor_command(arguments: argparse.Namespace) -> int:
    """Scan the requested tree and report every construct 2.0 changed."""

    try:
        result = scan_path(Path(arguments.path))
    except COMMAND_FAILURES as error:
        return report_failure(error)

    if arguments.output_format == JSON_FORMAT:
        print(render_json(_json_sections(result)))
    else:
        print(_render_text(result))

    if result.findings or result.parsed_nothing:
        return _FAILING_EXIT_CODE
    return 0


def _json_sections(result: ScanResult) -> tuple[ReportSection, ...]:
    """Describe the scan for a reader that is a script rather than a person."""

    return (
        ReportSection(
            key="findings",
            title="findings",
            columns=("file", "line", "construct", "fix"),
            rows=finding_rows(result.findings),
        ),
        ReportSection(
            key="skipped",
            title="skipped",
            columns=("file", "reason"),
            rows=skipped_rows(result.skipped),
        ),
        ReportSection(
            key="summary",
            title="summary",
            columns=("scanned", "files", "findings", "skipped"),
            rows=scan_summary(result),
        ),
    )


def _render_text(result: ScanResult) -> str:
    """Render the scan for a person, one block per finding.

    A finding is a sentence of explanation and a sentence of instruction, and neither
    survives being squeezed into a table cell beside the other. The block form is what
    makes the fix the thing the reader's eye lands on, which is the whole point of the
    command.
    """

    lines: list[str] = []
    for finding in result.findings:
        lines.append(f"{finding.path}:{finding.line}  {finding.construct}")
        lines.append(f"  what changed: {finding.change}")
        lines.append(f"  fix: {finding.fix}")
        lines.append("")

    for entry in result.skipped:
        lines.append(f"{entry.path}  could not be parsed: {entry.reason}")
        lines.append("")

    lines.append(_summary_line(result))
    return "\n".join(lines)


def _summary_line(result: ScanResult) -> str:
    """State what the scan covered and what it found, in one line."""

    if result.parsed_nothing:
        return (
            f"Scanned {_count(result.scanned, 'file')}: not one could be parsed, "
            "so nothing was checked."
        )

    if not result.findings:
        found = "nothing to change"
    else:
        files = len({finding.path for finding in result.findings})
        found = f"{_count(len(result.findings), 'finding')} in {_count(files, 'file')}"

    skipped = ""
    if result.skipped:
        skipped = f", {_count(len(result.skipped), 'file')} not parsed"
    return f"Scanned {_count(result.scanned, 'file')}: {found}{skipped}."


def _count(value: int, noun: str) -> str:
    """Render a count with its noun, pluralised."""

    return f"{value} {noun}" if value == 1 else f"{value} {noun}s"
