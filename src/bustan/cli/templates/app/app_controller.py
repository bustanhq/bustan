from bustan import Controller, Get
from .app_service import AppService

@Controller("/")
class AppController:
    def __init__(self, app_service: AppService):
        self.app_service = app_service

    @Get("/")
    def get_message(self) -> dict[str, str]:
        return self.app_service.get_message()
