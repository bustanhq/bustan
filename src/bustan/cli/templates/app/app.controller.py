from bustan import Controller, Get

from . import AppService


@Controller("/")
class AppController:
    def __init__(self, app_service: AppService) -> None:
        self.app_service = app_service

    @Get("/")
    def read_root(self) -> dict[str, str]:
        return self.app_service.get_message()
