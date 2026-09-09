"""CORS configuration types.

The policy value type itself is declared in :mod:`bustan.contracts.cors`, because a
transport adapter is what enforces the policy and an adapter may read the contracts and
nothing above them. It is named here as well, unchanged, because this is where the
package's security surface is assembled and where ``bustan.CorsOptions`` is exported
from.
"""

from __future__ import annotations

from ..contracts.cors import CorsOptions

__all__ = ("CorsOptions",)
