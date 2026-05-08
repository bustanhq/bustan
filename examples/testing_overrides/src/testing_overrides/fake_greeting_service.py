"""Test double used by the testing override example."""


class FakeGreetingService:
    def __init__(self, message: str) -> None:
        self.message = message

    def greet(self) -> str:
        return self.message