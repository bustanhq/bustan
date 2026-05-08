"""Greeting controller for the testing override example."""

from bustan import Controller, Get

from .greeting_service import GreetingService


@Controller("/greetings")
class GreetingController:
    def __init__(self, greeting_service: GreetingService) -> None:
        self.greeting_service = greeting_service

    @Get("/")
    def read_greeting(self) -> dict[str, str]:
        return {"message": self.greeting_service.greet()}