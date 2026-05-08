"""Catalog controller for the graph inspection example."""

from bustan import Controller, Get

from .catalog_service import CatalogService


@Controller("/catalog")
class CatalogController:
    def __init__(self, catalog_service: CatalogService) -> None:
        self.catalog_service = catalog_service

    @Get("/")
    def list_categories(self) -> list[str]:
        return self.catalog_service.list_categories()