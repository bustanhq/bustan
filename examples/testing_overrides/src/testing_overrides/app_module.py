"""Root module for the testing override example."""

from bustan import Module

from .greeting_controller import GreetingController
from .greeting_service import GreetingService


@Module(
    controllers=[GreetingController],
    providers=[GreetingService],
    exports=[GreetingService],
)
class AppModule:
    pass