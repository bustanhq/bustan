"""What a typed token resolves to is a claim only a type checker can settle.

A runtime test cannot tell the difference between a resolution that is typed and one
that is not: both hand back the same object. So the checker is run here, over a file
written for the purpose, and what is asserted is that it refuses the wrong-typed
assignment and accepts the right-typed one. Without the refusal the acceptance proves
nothing, because a signature returning an untyped value accepts everything.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

_RESOLVING_A_TYPED_TOKEN = """
from bustan import ApplicationContext, InjectionToken


class Clock:
    def now(self) -> int:
        return 0


CLOCK = InjectionToken[Clock]("CLOCK")


def right(context: ApplicationContext) -> Clock:
    return context.get(CLOCK)


def wrong(context: ApplicationContext) -> int:
    return context.get(CLOCK)
"""


def _type_checker() -> Path:
    """Return the ty executable of the environment the suite is running in."""

    beside_the_interpreter = Path(sys.executable).parent / "ty"
    if beside_the_interpreter.exists():
        return beside_the_interpreter
    found = shutil.which("ty")
    assert found is not None, "ty is a development dependency and must be installed to run this"
    return Path(found)


def _check(source: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Type check one source file on its own, outside the repository's own tree."""

    module_path = tmp_path / "resolution.py"
    module_path.write_text(source, encoding="utf-8")
    return subprocess.run(
        [str(_type_checker()), "check", "--output-format", "concise", str(module_path)],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPOSITORY_ROOT,
    )


def test_resolving_a_typed_token_into_the_wrong_type_is_a_type_error(tmp_path: Path) -> None:
    completed = _check(_RESOLVING_A_TYPED_TOKEN, tmp_path)
    diagnostics = completed.stdout + completed.stderr

    wrong_line = (
        _RESOLVING_A_TYPED_TOKEN.splitlines().index(
            "def wrong(context: ApplicationContext) -> int:"
        )
        + 2
    )

    assert completed.returncode != 0, diagnostics
    assert "invalid-return-type" in diagnostics, diagnostics
    assert "expected `int`, found `Clock`" in diagnostics, diagnostics
    assert f"resolution.py:{wrong_line}:" in diagnostics, diagnostics
    # The same file resolves the same token into the type the token declares, and that
    # line is not reported. One diagnostic, on the return that is actually wrong.
    assert diagnostics.count("resolution.py") == 1, diagnostics
