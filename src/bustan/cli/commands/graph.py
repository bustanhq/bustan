"""The ``bustan graph`` command: the module and provider graph an application compiled."""

from __future__ import annotations

import argparse
import re
from collections.abc import Mapping

from ...addons.discovery import DiscoveryService
from ...app.bootstrap import _create_app
from ..services.failures import COMMAND_FAILURES, report_failure
from ..services.reporting import ReportSection, add_format_option, render_report
from .routes import _load_root_module

# The row fields that name a module rather than describing a value.
_MODULE_NAME_FIELDS: tuple[str, ...] = ("module", "imports")

# How a module built by a factory describes itself: the class it was built from, and
# then the providers it was built with. Only the class is a name.
_BUILT_MODULE_REPR = re.compile(r"^DynamicModule\(module=<class '(?P<dotted>[\w.]+)'>")


def register_graph_command(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "graph",
        help="Render the module and provider graph an application compiles to.",
    )
    parser.add_argument(
        "target", help="Root module import path in the form package.module:RootModule"
    )
    add_format_option(parser)


def run_graph_command(arguments: argparse.Namespace) -> int:
    """Compile the target application and report the graph behind it."""

    try:
        sections = _build_graph_sections(arguments.target)
    except COMMAND_FAILURES as error:
        return report_failure(error)

    print(render_report(sections, arguments.output_format))
    return 0


def _build_graph_sections(target: str) -> tuple[ReportSection, ...]:
    """Read the compiled graph through the framework's own discovery surface.

    The service is constructed against the application rather than resolved out of it,
    because the graph is a property of every application, and asking for it should not
    require the caller to have imported the addon module that publishes it.
    """

    application = _create_app(_load_root_module(target), no_lifespan=True)
    discovery = DiscoveryService(application)
    return (
        ReportSection(
            key="modules",
            title="modules",
            columns=("module", "global", "imports", "controllers", "providers", "exports"),
            rows=tuple(_named_module_row(row) for row in discovery.modules()),
        ),
        ReportSection(
            key="providers",
            title="providers",
            columns=("module", "token", "scope", "resolver", "exported"),
            rows=tuple(_named_module_row(row) for row in discovery.providers()),
        ),
    )


def _named_module_row(row: Mapping[str, object]) -> Mapping[str, object]:
    """Return one discovery row with its module names reduced to names.

    A module that was built by a factory is described by its repr, and the repr of a
    built module carries the providers it was built with - which, for a configuration
    module, is every value the application resolved. This command reports the shape of
    an application, not its contents, so a module is named here and never described.
    """

    named = dict(row)
    for field in _MODULE_NAME_FIELDS:
        value = named.get(field)
        if isinstance(value, str):
            named[field] = _module_name(value)
        elif isinstance(value, tuple | list):
            named[field] = tuple(
                _module_name(item) if isinstance(item, str) else item for item in value
            )
    return named


def _module_name(name: str) -> str:
    """Reduce a discovered module name to the name of the class behind it."""

    match = _BUILT_MODULE_REPR.match(name)
    if match is None:
        return name
    return f"{match['dotted'].rsplit('.', 1)[-1]} (dynamic)"
