"""Feature module for request-local identity state."""

from bustan import Module

from .request_actor import RequestActor


@Module(providers=[RequestActor], exports=[RequestActor])
class IdentityModule:
    pass