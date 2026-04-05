"""Example showing cross-module provider visibility through exports."""

from bustan import Controller, create_app, Get, Injectable, Module


@Injectable
class UserService:
    def list_users(self) -> list[dict[str, str]]:
        return [{"name": "Moses"}, {"name": "Ada"}]


@Controller("/users")
class UserController:
    def __init__(self, user_service: UserService) -> None:
        self.user_service = user_service

    @Get("/")
    def list_users(self) -> list[dict[str, str]]:
        return self.user_service.list_users()


@Injectable
class AuthService:
    def issuer(self) -> str:
        return "bustan-auth"


@Module(
    controllers=[UserController],
    providers=[UserService],
    exports=[UserService],
)
class UsersModule:
    pass


@Module(
    providers=[AuthService],
    exports=[AuthService],
)
class AuthModule:
    pass


@Module(imports=[UsersModule, AuthModule])
class AppModule:
    pass


app = create_app(AppModule)
