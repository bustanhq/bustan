"""Root controller for the dynamic module example."""

from bustan import Controller, Get

from .cache_service import CacheService


@Controller("/")
class AppController:
    def __init__(self, cache_service: CacheService) -> None:
        self.cache_service = cache_service

    @Get("/")
    def index(self) -> dict[str, str]:
        return {"cached_value": self.cache_service.get("example-key")}