from bustan import Module

from . import AppController, AppService


@Module(controllers=[AppController], providers=[AppService], exports=[AppService])
class AppModule:
    pass
