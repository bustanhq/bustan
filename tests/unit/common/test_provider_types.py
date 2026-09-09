"""What a provider declaration cannot say is a claim only a type checker can settle.

The container refuses a malformed provider when an application is built, and a runtime
test can only show that the refusal happens then. The point of the value types is that
three of those mistakes stop being writable at all, which is a statement about what the
checker accepts. So the checker is run here, over files written for the purpose, and
what is asserted is that it reports the declaration that is wrong and says nothing about
the one beside it that is right. Without the silence the report proves nothing, because
a checker that rejected every declaration would produce it too.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

_PREAMBLE = """
from bustan import ClassProvider, FactoryProvider, InjectionToken, Injectable, ValueProvider


@Injectable
class Clock:
    def now(self) -> int:
        return 0


CLOCK = InjectionToken[Clock]("CLOCK")


def build_clock() -> Clock:
    return Clock()

"""

_A_KEY_NO_PROVIDER_HAS = (
    _PREAMBLE
    + """
right = ClassProvider(provide=CLOCK, use_class=Clock)
wrong = ClassProvider(provide=CLOCK, use_class=Clock, lifetime="singleton")
"""
)

_NO_TOKEN_TO_BIND = (
    _PREAMBLE
    + """
right = ValueProvider(provide=CLOCK, use_value=Clock())
wrong = ValueProvider(use_value=Clock())
"""
)

_TWO_TARGETS_IN_ONE_DECLARATION = (
    _PREAMBLE
    + """
right = FactoryProvider(provide=CLOCK, use_factory=build_clock)
wrong = FactoryProvider(provide=CLOCK, use_factory=build_clock, use_class=Clock)
"""
)


def _type_checker() -> Path:
    """Return the ty executable of the environment the suite is running in."""

    beside_the_interpreter = Path(sys.executable).parent / "ty"
    if beside_the_interpreter.exists():
        return beside_the_interpreter
    found = shutil.which("ty")
    assert found is not None, "ty is a development dependency and must be installed to run this"
    return Path(found)


def _assert_only_the_wrong_line_is_reported(source: str, rule: str, tmp_path: Path) -> None:
    """Check one source file and assert the refusal, and the silence beside it."""

    module_path = tmp_path / "declaration.py"
    module_path.write_text(source, encoding="utf-8")
    completed = subprocess.run(
        [str(_type_checker()), "check", "--output-format", "concise", str(module_path)],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPOSITORY_ROOT,
    )
    diagnostics = completed.stdout + completed.stderr
    lines = source.splitlines()
    wrong_line = next(i for i, line in enumerate(lines, 1) if line.startswith("wrong = "))

    assert completed.returncode != 0, diagnostics
    assert rule in diagnostics, diagnostics
    assert f"declaration.py:{wrong_line}:" in diagnostics, diagnostics
    # The declaration above it says the same thing correctly and is not reported. One
    # diagnostic, on the line that is actually wrong.
    assert diagnostics.count("declaration.py") == 1, diagnostics


def test_a_key_no_provider_has_is_a_type_error(tmp_path: Path) -> None:
    _assert_only_the_wrong_line_is_reported(_A_KEY_NO_PROVIDER_HAS, "unknown-argument", tmp_path)


def test_a_declaration_with_no_token_to_bind_is_a_type_error(tmp_path: Path) -> None:
    _assert_only_the_wrong_line_is_reported(_NO_TOKEN_TO_BIND, "missing-argument", tmp_path)


def test_two_targets_in_one_declaration_is_a_type_error(tmp_path: Path) -> None:
    _assert_only_the_wrong_line_is_reported(
        _TWO_TARGETS_IN_ONE_DECLARATION, "unknown-argument", tmp_path
    )
