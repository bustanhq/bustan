"""Root controller for the multi-module example."""

from bustan import Controller, Get

from .auth_service import AuthService
from .users_service import UserService


@Controller("/users")
class UserController:
    def __init__(self, user_service: UserService, auth_service: AuthService) -> None:
        self.user_service = user_service
        self.auth_service = auth_service

    @Get("/")
    def list_users(self) -> dict[str, object]:
        return {
            "issuer": self.auth_service.issuer(),
            "users": self.user_service.list_users(),
        }