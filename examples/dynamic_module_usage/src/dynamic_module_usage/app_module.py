"""Root module for the dynamic module example."""

from bustan import Module

from .app_controller import AppController
from .cache_module import CacheModule


@Module(
    imports=[CacheModule.register("prod:")],
    controllers=[AppController],
)
class AppModule:
    pass