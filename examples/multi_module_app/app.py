"""Example showing cross-module provider visibility through exports."""

from star import controller, create_app, get, injectable, module


@injectable
class UserService:
    def list_users(self) -> list[dict[str, str]]:
        return [{"name": "Moses"}, {"name": "Ada"}]


@controller("/users")
class UserController:
    def __init__(self, user_service: UserService) -> None:
        self.user_service = user_service

    @get("/")
    def list_users(self) -> list[dict[str, str]]:
        return self.user_service.list_users()


@injectable
class AuthService:
    def issuer(self) -> str:
        return "star-auth"


@module(
    controllers=[UserController],
    providers=[UserService],
    exports=[UserService],
)
class UsersModule:
    pass


@module(
    providers=[AuthService],
    exports=[AuthService],
)
class AuthModule:
    pass


@module(imports=[UsersModule, AuthModule])
class AppModule:
    pass


app = create_app(AppModule)
