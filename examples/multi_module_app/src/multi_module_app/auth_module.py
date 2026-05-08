"""Auth feature module for the multi-module example."""

from bustan import Module

from .auth_service import AuthService


@Module(providers=[AuthService], exports=[AuthService])
class AuthModule:
    pass