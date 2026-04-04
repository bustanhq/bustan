"""Generate the public API reference from stable-module docstrings."""

from __future__ import annotations

import argparse
import importlib
import inspect
from enum import Enum
from pathlib import Path
from types import ModuleType
from collections.abc import Sequence
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "docs" / "API_REFERENCE.md"
GENERATE_COMMAND = "uv run python scripts/generate_api_reference.py"

STABLE_MODULES = (
    "star",
    "star.testing",
    "star.errors",
)

MODULE_IMPORT_EXAMPLES: dict[str, tuple[str, ...]] = {
    "star": (
        "from star import __version__, controller, create_app, get, injectable, module",
        "from star import ExceptionFilter, Guard, Interceptor, Pipe",
    ),
    "star.testing": (
        "from star.testing import create_test_app, create_test_module, override_provider",
    ),
    "star.errors": (
        "from star.errors import ProviderResolutionError, RouteDefinitionError, StarError",
    ),
}

SPECIAL_VALUE_DOCS: dict[tuple[str, str], str] = {
    ("star", "__version__"): "Installed distribution version string for the star package.",
}

SPECIAL_CLASS_ATTRIBUTES: dict[tuple[str, str], dict[str, str]] = {
    (
        "star",
        "ExceptionFilter",
    ): {
        "exception_types": "Tuple of exception classes the filter handles.",
    },
}


def main(argv: Sequence[str] | None = None) -> int:
    """Render or validate the checked-in public API reference."""

    arguments = _parse_args(argv)
    if arguments.check:
        return check_api_reference()
    return write_api_reference()


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments for the generator utility."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when docs/API_REFERENCE.md does not match the generated output",
    )
    return parser.parse_args(argv)


def write_api_reference(output_path: Path = OUTPUT_PATH) -> int:
    """Render the API reference and write it to disk."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_api_reference(), encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


def check_api_reference(output_path: Path = OUTPUT_PATH) -> int:
    """Return a non-zero exit code when the checked-in API reference is stale."""

    try:
        existing_reference = output_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"{output_path} is missing. Run `{GENERATE_COMMAND}`.")
        return 1

    rendered_reference = render_api_reference()
    if existing_reference != rendered_reference:
        print(f"{output_path} is out of sync. Run `{GENERATE_COMMAND}`.")
        return 1

    print(f"{output_path} is up to date.")
    return 0


def render_api_reference() -> str:
    """Return the complete public API reference as Markdown."""

    sections = [
        "# API Reference",
        "",
        "This document is generated from docstrings in the stable public modules.",
        f"Regenerate it with `{GENERATE_COMMAND}`.",
        "",
        "Stable modules:",
        "- `star`",
        "- `star.testing`",
        "- `star.errors`",
        "",
    ]

    for module_name in STABLE_MODULES:
        module = importlib.import_module(module_name)
        sections.extend(_render_module(module_name, module))

    return "\n".join(sections).rstrip() + "\n"


def _render_module(module_name: str, module: ModuleType) -> list[str]:
    """Render one stable module section."""

    lines = [f"## `{module_name}`", ""]

    module_doc = inspect.getdoc(module)
    if module_doc is not None:
        lines.extend((module_doc, ""))

    import_examples = MODULE_IMPORT_EXAMPLES.get(module_name, ())
    if import_examples:
        lines.extend(("### Import", "", "```python"))
        lines.extend(import_examples)
        lines.extend(("```", ""))

    lines.extend(("### Exports", ""))
    for export_name in getattr(module, "__all__", ()):  # pragma: no branch - stable modules all define __all__
        exported_object = getattr(module, export_name)
        lines.extend(_render_export(module_name, export_name, exported_object))

    return lines


def _render_export(module_name: str, export_name: str, exported_object: object) -> list[str]:
    """Render one exported symbol section."""

    if inspect.isclass(exported_object):
        return _render_class_export(module_name, export_name, exported_object)

    if inspect.isroutine(exported_object):
        return _render_callable_export(module_name, export_name, exported_object)

    return _render_value_export(module_name, export_name, exported_object)


def _render_callable_export(module_name: str, export_name: str, exported_object: object) -> list[str]:
    """Render a function or callable export."""

    lines = [f"#### `{export_name}`", ""]
    lines.extend(
        (
            "```python",
            f"def {_format_signature(export_name, exported_object)}",
            "```",
            "",
        )
    )
    lines.extend(_render_origin_line(exported_object))
    lines.extend(_render_doc_paragraphs(inspect.getdoc(exported_object)))
    lines.append("")
    return lines


def _render_class_export(module_name: str, export_name: str, exported_object: type[object]) -> list[str]:
    """Render a class export, including public methods and attributes."""

    lines = [f"#### `{export_name}`", ""]
    lines.extend(
        (
            "```python",
            _format_class_declaration(export_name, exported_object),
            "```",
            "",
        )
    )
    lines.extend(_render_origin_line(exported_object))
    lines.extend(_render_doc_paragraphs(inspect.getdoc(exported_object)))

    attributes = _render_class_attributes(module_name, export_name, exported_object)
    methods = _render_class_methods(exported_object)
    if attributes:
        lines.extend(("", "##### Attributes", ""))
        lines.extend(attributes)
    if methods:
        lines.extend(("", "##### Methods", ""))
        lines.extend(methods)

    lines.append("")
    return lines


def _render_value_export(module_name: str, export_name: str, exported_object: object) -> list[str]:
    """Render a value export such as __version__."""

    lines = [f"#### `{export_name}`", ""]
    lines.extend(_render_origin_line(exported_object))

    value_doc = SPECIAL_VALUE_DOCS.get((module_name, export_name)) or inspect.getdoc(exported_object)
    lines.extend(_render_doc_paragraphs(value_doc))
    lines.extend(("", f"Current value: `{exported_object}`", ""))
    return lines


def _render_class_attributes(
    module_name: str,
    export_name: str,
    exported_object: type[object],
) -> list[str]:
    """Render documented public class attributes."""

    documented_attributes = SPECIAL_CLASS_ATTRIBUTES.get((module_name, export_name), {})
    lines: list[str] = []

    for attribute_name, attribute_doc in documented_attributes.items():
        if attribute_name not in exported_object.__dict__:
            continue
        attribute_value = exported_object.__dict__[attribute_name]
        lines.extend(
            (
                f"- `{attribute_name}`",
                f"  Default: `{attribute_value!r}`",
                f"  {attribute_doc}",
            )
        )

    return lines


def _render_class_methods(exported_object: type[object]) -> list[str]:
    """Render public methods defined directly on a class."""

    lines: list[str] = []

    for method_name, member in exported_object.__dict__.items():
        if method_name.startswith("_"):
            continue

        method = _unwrap_descriptor(member)
        if method is None:
            continue

        lines.append(f"- `{_format_signature(method_name, method)}`")
        method_doc = inspect.getdoc(method)
        if method_doc is not None:
            lines.append(f"  {method_doc}")

    return lines


def _render_origin_line(exported_object: object) -> list[str]:
    """Render the source module line for an exported object."""

    object_module = getattr(exported_object, "__module__", None)
    if object_module is None:
        return []
    return [f"Defined in `{object_module}`.", ""]


def _render_doc_paragraphs(docstring: str | None) -> list[str]:
    """Render a docstring as Markdown paragraphs."""

    if docstring is None:
        return ["No user-facing documentation provided."]
    return docstring.splitlines()


def _format_class_declaration(export_name: str, exported_object: type[object]) -> str:
    """Return the display declaration for a class export."""

    base_names = [base.__name__ for base in exported_object.__bases__ if base is not object]
    if not base_names:
        return f"class {export_name}"
    return f"class {export_name}({', '.join(base_names)})"


def _format_signature(name: str, exported_object: object) -> str:
    """Return a readable signature for a callable."""

    try:
        signature = inspect.signature(cast(Any, exported_object))
    except (TypeError, ValueError):
        return f"{name}(...)"

    rendered_parameters: list[str] = []
    inserted_kw_separator = False
    saw_positional_only = False

    for parameter in signature.parameters.values():
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY and not inserted_kw_separator:
            rendered_parameters.append("*")
            inserted_kw_separator = True
        rendered_parameters.append(_format_parameter(parameter))
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
            saw_positional_only = True

    if saw_positional_only:
        positional_only_count = sum(
            1 for parameter in signature.parameters.values() if parameter.kind is inspect.Parameter.POSITIONAL_ONLY
        )
        rendered_parameters.insert(positional_only_count, "/")

    rendered_signature = f"{name}({', '.join(rendered_parameters)})"
    if signature.return_annotation is not inspect.Signature.empty:
        rendered_signature += f" -> {_format_annotation(signature.return_annotation)}"
    return rendered_signature


def _format_parameter(parameter: inspect.Parameter) -> str:
    """Render one signature parameter."""

    prefix = ""
    if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
        prefix = "*"
    elif parameter.kind is inspect.Parameter.VAR_KEYWORD:
        prefix = "**"

    rendered_parameter = f"{prefix}{parameter.name}"
    if parameter.annotation is not inspect.Signature.empty:
        rendered_parameter += f": {_format_annotation(parameter.annotation)}"
    if parameter.default is not inspect.Signature.empty:
        rendered_parameter += f" = {_format_default(parameter.default)}"
    return rendered_parameter


def _format_annotation(annotation: object) -> str:
    """Render an annotation without exposing internal repr noise where possible."""

    if isinstance(annotation, str):
        return annotation

    if inspect.isclass(annotation):
        return annotation.__qualname__

    module_name = getattr(annotation, "__module__", "")
    qualname = getattr(annotation, "__qualname__", None)
    if qualname is not None and module_name in {"builtins", ""}:
        return qualname

    rendered_annotation = repr(annotation)
    if rendered_annotation.startswith("<class '") and rendered_annotation.endswith("'>"):
        return rendered_annotation.removeprefix("<class '").removesuffix("'>").split(".")[-1]
    if rendered_annotation.startswith("typing."):
        rendered_annotation = rendered_annotation.removeprefix("typing.")
    if rendered_annotation.startswith("collections.abc."):
        rendered_annotation = rendered_annotation.removeprefix("collections.abc.")
    return rendered_annotation


def _format_default(default: object) -> str:
    """Render a default value for documentation output."""

    if isinstance(default, Enum):
        return f"{type(default).__name__}.{default.name}"
    return repr(default)


def _unwrap_descriptor(member: object) -> object | None:
    """Return the underlying callable for functions and descriptors."""

    if isinstance(member, (staticmethod, classmethod)):
        return member.__func__
    if inspect.isfunction(member):
        return member
    return None


if __name__ == "__main__":
    raise SystemExit(main())