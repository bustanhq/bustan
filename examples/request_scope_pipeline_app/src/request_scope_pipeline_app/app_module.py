"""Root module for the request-scoped pipeline example."""

from bustan import Module

from .account_controller import AccountController
from .authenticated_guard import AuthenticatedGuard
from .profile_service import ProfileService
from .request_envelope_interceptor import RequestEnvelopeInterceptor
from .request_identity import RequestIdentity


@Module(
    controllers=[AccountController],
    providers=[
        ProfileService,
        RequestIdentity,
        AuthenticatedGuard,
        RequestEnvelopeInterceptor,
    ],
    exports=[ProfileService],
)
class AppModule:
    pass