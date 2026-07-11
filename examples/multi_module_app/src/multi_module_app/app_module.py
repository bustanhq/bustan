"""Root module for the multi-module example."""

from bustan import Module

from .auth_module import AuthModule
from .user_controller import UserController
from .users_module import UsersModule


@Module(imports=[UsersModule, AuthModule], controllers=[UserController])
class AppModule:
    pass