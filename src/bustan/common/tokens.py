"""The identity rule every table keyed by a provider token shares.

This module imports nothing from the package. The rule is needed both by the injection
markers and by the registry that reads them, and keeping it free of package imports is
what lets either side reach it without either one importing the other.
"""

from __future__ import annotations

type TokenKey = tuple[type[object], object]


def token_identity(token: object) -> TokenKey:
    """Return a token's type-aware identity.

    Python maps equal keys onto one dict entry, so a string enum member and the bare
    string it equals collide. Pairing a token with its type keeps the two apart wherever
    the framework needs to tell one declaration from another.
    """

    return (type(token), token)
