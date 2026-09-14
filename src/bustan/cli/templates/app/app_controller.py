from bustan import Controller, Get

from .app_service import AppService


@Controller("/")
class AppController:
    def __init__(self, app_service: AppService):
        self.app_service = app_service

    # Async because it never blocks. A handler that does blocking work, such as a
    # synchronous database call, is written with def and run on a worker thread.
    @Get("/")
    async def get_message(self) -> dict[str, str]:
        return self.app_service.get_message()
