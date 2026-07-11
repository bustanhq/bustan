"""Users feature module for the multi-module example."""

from bustan import Module

from .users_service import UserService


@Module(providers=[UserService], exports=[UserService])
class UsersModule:
    pass