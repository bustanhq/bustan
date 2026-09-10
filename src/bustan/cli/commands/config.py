"""The ``bustan config`` command: the configuration an application resolved."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import Any, cast

from ...app.bootstrap import _create_app
from ...configuration import CONFIG_VALUES
from ...kernel.errors import ProviderResolutionError
from ...observability.logger import DEFAULT_REDACTED_KEYS, redact
from ..services.failures import COMMAND_FAILURES, report_failure
from ..services.reporting import ReportSection, add_format_option, render_report
from .routes import _load_root_module

_NO_CONFIGURATION = (
    "This application resolves no configuration, so there is nothing to report. "
    "Configuration reaches an application through ConfigModule.for_root(), imported by "
    "the root module."
)

_NOT_A_MAPPING = "The application's configuration resolved to {kind}, not to a mapping of values."


def register_config_command(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "config",
        help=(
            "Render the configuration an application resolved, withholding the value of "
            "every key whose name reads as a credential."
        ),
        description=(
            "Render the configuration an application resolved. Withholding is a match on "
            "the text of a key's name, not a guarantee about the value behind it: a "
            "secret held under a name that does not read as one is printed in full, and "
            "this report is often the output a reader pastes into a bug report."
        ),
    )
    parser.add_argument(
        "target", help="Root module import path in the form package.module:RootModule"
    )
    parser.add_argument(
        "--redacted",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Withhold the value of every key whose name reads as a credential. "
            "On by default; pass --no-redacted to print the values in full."
        ),
    )
    add_format_option(parser)


def run_config_command(arguments: argparse.Namespace) -> int:
    """Compile the target application and report the configuration it resolved."""

    try:
        values = _resolve_config_values(arguments.target)
    except COMMAND_FAILURES as error:
        return report_failure(error)

    if arguments.redacted:
        values = cast(dict[str, Any], redact(values, redaction_keys(values)))

    section = ReportSection(
        key="config",
        title="config",
        columns=("key", "value"),
        rows=tuple({"key": key, "value": values[key]} for key in sorted(values)),
    )
    print(render_report((section,), arguments.output_format))
    return 0


def _resolve_config_values(target: str) -> dict[str, Any]:
    """Return the configuration the target application resolved.

    An application that registers none is a use of the command that was answered, not
    a fault, so the refusal it produces is replaced with the sentence that says how
    configuration reaches an application in the first place.
    """

    application = _create_app(_load_root_module(target), no_lifespan=True)
    try:
        values = application.get(CONFIG_VALUES)
    except ProviderResolutionError as error:
        raise ProviderResolutionError(_NO_CONFIGURATION) from error

    if not isinstance(values, Mapping):
        raise ValueError(_NOT_A_MAPPING.format(kind=type(values).__name__))
    return {str(key): value for key, value in values.items()}


def redaction_keys(values: Mapping[str, object]) -> frozenset[str]:
    """Name every key whose value is withheld from this application's configuration.

    The shared redaction matches a field by its whole name, which is what a header or a
    structured log field needs: those names are fixed and short. A configuration key is
    conventionally prefixed with the service it belongs to, so matching whole names
    alone would withhold PASSWORD and print DATABASE_PASSWORD standing beside it. The
    defaults are therefore widened, once, with the keys this application actually holds
    that carry one of those names inside a longer one. Redaction itself is unchanged:
    the shared helper still decides what a match means and how deep it looks.

    A key is matched on the text of its name, so a name that merely contains a
    credential's name is withheld too. Withholding a value that did not need it costs
    the reader one lookup; printing one that did cannot be taken back.
    """

    matched = {
        key.lower()
        for key in values
        if any(default in key.lower() for default in DEFAULT_REDACTED_KEYS)
    }
    return DEFAULT_REDACTED_KEYS | frozenset(matched)
