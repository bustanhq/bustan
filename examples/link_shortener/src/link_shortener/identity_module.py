"""Who is calling, as a unit other modules can import."""

from __future__ import annotations

from bustan import AUTHENTICATOR_REGISTRY, FactoryProvider, Module

from .bearer_authenticator import BearerAuthenticator


def _registry(authenticator: BearerAuthenticator) -> dict[str, object]:
    """Map each strategy name a route can ask for to the thing that answers it."""
    return {"bearer": authenticator}


@Module(
    providers=[
        BearerAuthenticator,
        FactoryProvider(
            provide=AUTHENTICATOR_REGISTRY,
            use_factory=_registry,
            inject=(BearerAuthenticator,),
        ),
    ],
    exports=[AUTHENTICATOR_REGISTRY],
)
class IdentityModule:
    """Any module with an authenticated route imports this.

    The registry is checked while routes compile, so a module that forgets the import is
    refused at startup with the name of the handler that needed it, not on the first
    request a caller makes.
    """
