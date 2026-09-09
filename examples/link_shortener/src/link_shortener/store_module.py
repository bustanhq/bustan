"""The store, as a unit other modules can import."""

from __future__ import annotations

from bustan import Module

from .link_store import LinkStore


@Module(providers=[LinkStore], exports=[LinkStore])
class StoreModule:
    """Owns the connection and lends it out.

    A provider declared in the root module is not visible to a feature module: modules
    are real boundaries, and crossing one is an import, not an accident. Anything that
    needs the store imports this.
    """
