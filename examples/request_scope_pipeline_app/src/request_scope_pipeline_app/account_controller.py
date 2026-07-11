"""Request-scoped controller for the pipeline example."""

from bustan import Controller, Get, Scope, UseGuards, UseInterceptors

from .authenticated_guard import AuthenticatedGuard
from .profile_service import ProfileService
from .request_envelope_interceptor import RequestEnvelopeInterceptor
from .request_identity import RequestIdentity


@UseGuards(AuthenticatedGuard)
@UseInterceptors(RequestEnvelopeInterceptor)
@Controller("/account", scope=Scope.REQUEST)
class AccountController:
    def __init__(
        self,
        profile_service: ProfileService,
        request_identity: RequestIdentity,
    ) -> None:
        self.profile_service = profile_service
        self.request_identity = request_identity

    @Get("/me")
    def read_current_account(self) -> dict[str, str]:
        user_id = self.request_identity.require_user_id()
        profile = self.profile_service.read_profile(user_id)
        return {
            "path": self.request_identity.path,
            **profile,
        }