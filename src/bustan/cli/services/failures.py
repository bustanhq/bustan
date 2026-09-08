"""How a command reports a failure it can explain rather than raising it.

A command line tool answers an operator, not a debugger. A stack trace tells that
reader nothing they can act on and hides the one sentence that would, so every failure
the tool can name is printed as that sentence and reported through the exit status.
"""

from __future__ import annotations

import sys

from ...kernel.errors import BustanError

# The failures a command turns into a message. The first four are what loading a target
# out of the caller's own tree can raise before the framework sees it at all: a bad
# import path, a module that does not import, an unreadable file, a malformed argument.
# BustanError is every refusal the framework itself states, and it is here because a
# root module that cannot be resolved is the caller's mistake to fix rather than ours.
COMMAND_FAILURES: tuple[type[Exception], ...] = (
    AttributeError,
    ImportError,
    OSError,
    ValueError,
    BustanError,
)


def report_failure(error: Exception) -> int:
    """Print what went wrong on stderr and return the failing exit status.

    An exception raised with no message still has to say something, so the type name
    stands in: an empty line followed by a non-zero exit tells the reader nothing.
    """

    print(str(error) or type(error).__name__, file=sys.stderr)
    return 1
