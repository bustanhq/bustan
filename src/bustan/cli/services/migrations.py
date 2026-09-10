"""The codebase scan behind ``bustan doctor``.

2.0 is a clean break: the framework carries no compatibility shim for a construct it
changed, so an application that used one fails at import, at build, or at the first
request that reaches it. This scan is what stands in for those shims. It reads a tree
with ``ast`` rather than importing it, because the code it is looking for is exactly
the code that no longer imports, and reports every construct it recognises with the
change that reached it and the edit that answers it.

A rule earns its place here only when the construct it names really did change and the
scan can prove the construct is present from the source alone. A rule that guesses
costs its reader more than the check saves them.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ...kernel.errors import InvalidPipelineError
from ...security.throttler import _window_seconds

# Directories a scan never descends into: virtual environments, caches, build output
# and version control. A tree that holds an installed copy of a dependency would
# otherwise be reported against the dependency's own source, which its user cannot fix.
EXCLUDED_DIRECTORIES: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "site-packages",
        "venv",
    }
)

# The packages the 2.0 layout renamed, longest prefix first so that a module under
# `bustan.platform.http` is reported against the package that really holds it.
RENAMED_PACKAGES: tuple[tuple[str, str], ...] = (
    ("bustan.platform.http", "bustan.runtime"),
    ("bustan.platform", "bustan.runtime"),
    ("bustan.core", "bustan.kernel"),
    ("bustan.logger", "bustan.observability"),
    ("bustan.config", "bustan.configuration"),
)

_INTERNAL_PATH_NOTE = (
    "Every one of these packages is internal, so prefer the same symbol from bustan, "
    "bustan.errors or bustan.testing where one of them exports it."
)


@dataclass(frozen=True, slots=True)
class MigrationFinding:
    """One construct 2.0 changed, found at one place in the scanned tree."""

    path: str
    line: int
    construct: str
    change: str
    fix: str

    def sort_key(self) -> tuple[str, int, str]:
        """Order findings by where they are, so two scans of a tree read alike."""

        return (self.path, self.line, self.construct)


@dataclass(frozen=True, slots=True)
class SkippedFile:
    """A file the scan could not read, and why.

    A file that cannot be parsed is not a file with nothing in it, so it is reported
    rather than passed over: the reader has to know which parts of their tree the
    answer does not cover.
    """

    path: str
    reason: str


@dataclass(frozen=True, slots=True)
class ScanResult:
    """What one scan looked at and what it found."""

    root: str
    scanned: int
    findings: tuple[MigrationFinding, ...]
    skipped: tuple[SkippedFile, ...]

    @property
    def parsed_nothing(self) -> bool:
        """Whether the scan read not one of the files it was handed.

        A scan that parsed nothing checked nothing, so its silence about findings says
        nothing about the tree and a caller must not read it as a clean result. A tree
        holding no Python files is not this case: there was nothing to parse, rather
        than nothing that could be.
        """

        return self.scanned > 0 and len(self.skipped) == self.scanned


def scan_path(root: Path) -> ScanResult:
    """Scan a file or a directory tree for constructs 2.0 changed."""

    if not root.exists():
        raise ValueError(f"Nothing to scan at {root}")

    findings: list[MigrationFinding] = []
    skipped: list[SkippedFile] = []
    scanned = 0
    for path in _python_files(root):
        scanned += 1
        display = _display_path(path, root)
        tree = _parse(path, display, skipped)
        if tree is None:
            continue
        findings.extend(_scan_module(tree, display))

    return ScanResult(
        root=str(root),
        scanned=scanned,
        findings=tuple(sorted(findings, key=MigrationFinding.sort_key)),
        skipped=tuple(skipped),
    )


def _parse(path: Path, display: str, skipped: list[SkippedFile]) -> ast.Module | None:
    """Parse one file, recording it as skipped when it cannot be read."""

    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError) as error:
        skipped.append(SkippedFile(path=display, reason=str(error)))
        return None


def _python_files(root: Path) -> Iterator[Path]:
    """Yield the Python files under *root*, in a stable order."""

    if root.is_file():
        yield root
        return

    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if any(part in EXCLUDED_DIRECTORIES for part in relative.parts):
            continue
        yield path


def _display_path(path: Path, root: Path) -> str:
    """Name a file the way the caller named the tree it is in."""

    if root.is_file():
        return str(path)
    return str(path.relative_to(root))


def _scan_module(tree: ast.Module, path: str) -> Iterator[MigrationFinding]:
    """Report every construct the rules recognise in one parsed module."""

    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            yield from _check_imports(node, path)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield from _check_method_shape(node, path)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            yield from _check_decorators(node, path)


def _check_imports(node: ast.Import | ast.ImportFrom, path: str) -> Iterator[MigrationFinding]:
    """Report imports of a renamed package or of a name that no longer exists."""

    for module in _imported_modules(node):
        renamed = _renamed_package(module)
        if renamed is not None:
            old, new = renamed
            yield MigrationFinding(
                path=path,
                line=node.lineno,
                construct=module,
                change=f"The {old} package is now {new}.",
                fix=f"Import {new}{module[len(old) :]} instead. {_INTERNAL_PATH_NOTE}",
            )

    if isinstance(node, ast.ImportFrom) and node.module == "bustan.adapters.asgi":
        yield from _check_removed_asgi_names(node, path)


def _imported_modules(node: ast.Import | ast.ImportFrom) -> tuple[str, ...]:
    """Return the module paths one import statement names.

    A relative import names no package this scan can resolve, so it is left alone
    rather than guessed at from the file's position in the tree.
    """

    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if node.level or node.module is None:
        return ()
    return (node.module,)


def _renamed_package(module: str) -> tuple[str, str] | None:
    """Return the rename that covers *module*, if one does."""

    for old, new in RENAMED_PACKAGES:
        if module == old or module.startswith(f"{old}."):
            return (old, new)
    return None


def _check_removed_asgi_names(node: ast.ImportFrom, path: str) -> Iterator[MigrationFinding]:
    """Report the ASGI adapter export that the request-limit contract replaced."""

    for alias in node.names:
        if alias.name != "RequestBodyTooLarge":
            continue
        yield MigrationFinding(
            path=path,
            line=node.lineno,
            construct="bustan.adapters.asgi.RequestBodyTooLarge",
            change=(
                "bustan.adapters.asgi no longer exports RequestBodyTooLarge. An oversized "
                "body is refused by the request limits and answered 413 rather than 500."
            ),
            fix="Import RequestBodyTooLargeError from bustan.errors instead.",
        )


def _check_method_shape(
    node: ast.FunctionDef | ast.AsyncFunctionDef, path: str
) -> Iterator[MigrationFinding]:
    """Report a method written against a protocol whose shape 2.0 changed.

    The match is on the method name together with the parameter names it was declared
    with, because that pair is what identifies an implementation of the old protocol.
    An implementation is not required to inherit from the protocol it satisfies, so
    there is no base class to match on instead.
    """

    parameters = _parameter_names(node)
    for rule in _METHOD_RULES:
        if node.name != rule.method or not rule.required.issubset(parameters):
            continue
        if rule.forbidden & parameters:
            continue
        yield MigrationFinding(
            path=path,
            line=node.lineno,
            construct=rule.construct,
            change=rule.change,
            fix=rule.fix,
        )


def _parameter_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    """Return every parameter name a function declares, however it declares it."""

    arguments = node.args
    named: list[ast.arg] = [
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
    ]
    return frozenset(argument.arg for argument in named)


@dataclass(frozen=True, slots=True)
class _MethodRule:
    """One protocol method whose shape changed, matched by its parameter names."""

    construct: str
    method: str
    required: frozenset[str]
    forbidden: frozenset[str]
    change: str
    fix: str


_METHOD_RULES: tuple[_MethodRule, ...] = (
    _MethodRule(
        construct="ThrottlerStorage.increment",
        method="increment",
        required=frozenset({"key", "ttl"}),
        forbidden=frozenset(),
        change=(
            "ThrottlerStorage declares one asynchronous count_request(key, ttl, limit) in "
            "place of increment and get_ttl."
        ),
        fix=(
            "Replace increment and get_ttl with "
            "'async def count_request(self, key: str, ttl: int, limit: int) -> ThrottleState', "
            "counting the request and reporting the key's state in one step, and do not count "
            "a request against a window that is already full."
        ),
    ),
    _MethodRule(
        construct="ThrottlerStorage.get_ttl",
        method="get_ttl",
        required=frozenset({"key"}),
        forbidden=frozenset(),
        change=(
            "ThrottlerStorage declares one asynchronous count_request(key, ttl, limit) in "
            "place of increment and get_ttl."
        ),
        fix=(
            "Report the seconds until the window clears as ThrottleState.reset_after from "
            "count_request, rather than from a second call."
        ),
    ),
    _MethodRule(
        construct="MetricsSink.record_request",
        method="record_request",
        required=frozenset({"labels"}),
        forbidden=frozenset({"duration_seconds"}),
        change="MetricsSink.record_request gained a duration_seconds keyword.",
        fix=(
            "Accept 'duration_seconds: float' as a keyword-only parameter. A sink without it "
            "is still called with the labels alone, so the request is counted but never timed."
        ),
    ),
    _MethodRule(
        construct="TraceSpan.finish",
        method="finish",
        required=frozenset({"status_code"}),
        forbidden=frozenset(),
        change=(
            "TraceSpan follows OpenTelemetry's span model: set_attribute, set_status, "
            "record_exception and end, in place of finish(status_code=..., error=...)."
        ),
        fix=(
            "Rename finish to end and take no arguments. The status arrives beforehand "
            "through set_status(SpanStatus, description=...), and the exception through "
            "record_exception(error)."
        ),
    ),
    _MethodRule(
        construct="RequestTracer.start_span",
        method="start_span",
        required=frozenset({"labels"}),
        forbidden=frozenset({"kind", "attributes"}),
        change=(
            "RequestTracer.start_span takes the span kind, its attributes and the caller's "
            "span context in place of labels."
        ),
        fix=(
            "Declare 'start_span(self, name: str, *, kind: SpanKind, "
            "attributes: Mapping[str, str], context: SpanContext) -> TraceSpan'. The labels "
            "arrive as attributes, and context names the trace the caller was already in."
        ),
    ),
)


def _check_decorators(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, path: str
) -> Iterator[MigrationFinding]:
    """Report a decorator whose arguments 2.0 began to check."""

    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or _decorator_name(decorator.func) != "RateLimit":
            continue
        window = _keyword_string(decorator, "window")
        if window is None or _window_is_readable(window):
            continue
        yield MigrationFinding(
            path=path,
            line=decorator.lineno,
            construct="RateLimit",
            change=(
                "RateLimit reads its window where the window is written, so a window the "
                "framework cannot read stops the build instead of answering 500 on every "
                "request the route serves."
            ),
            fix=(
                f"Write the window as a count and a unit, such as '60s', '5m', '1h' or '1d'. "
                f"{window!r} cannot be read."
            ),
        )


def _decorator_name(func: ast.expr) -> str | None:
    """Return the name a decorator was applied under, however it was imported."""

    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _keyword_string(call: ast.Call, name: str) -> str | None:
    """Return a keyword argument's value when it was written as a string literal."""

    for keyword in call.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            value = keyword.value.value
            return value if isinstance(value, str) else None
    return None


def _window_is_readable(window: str) -> bool:
    """Ask the throttler itself whether it can read a declared window.

    The question is put to the parser the decorator uses rather than to a second copy
    of its rules, so this scan cannot come to disagree with the framework about which
    windows are valid.
    """

    try:
        _window_seconds(window)
    except InvalidPipelineError:
        return False
    return True


def scan_summary(result: ScanResult) -> tuple[Mapping[str, object], ...]:
    """Return the one-row summary that closes a doctor report."""

    return (
        {
            "scanned": result.scanned,
            "findings": len(result.findings),
            "files": len({finding.path for finding in result.findings}),
            "skipped": len(result.skipped),
        },
    )


def finding_rows(findings: Sequence[MigrationFinding]) -> tuple[Mapping[str, object], ...]:
    """Return findings as report rows, in the order they were found."""

    return tuple(
        {
            "file": finding.path,
            "line": finding.line,
            "construct": finding.construct,
            "change": finding.change,
            "fix": finding.fix,
        }
        for finding in findings
    )


def skipped_rows(skipped: Sequence[SkippedFile]) -> tuple[Mapping[str, object], ...]:
    """Return unparsed files as report rows."""

    return tuple({"file": entry.path, "reason": entry.reason} for entry in skipped)
