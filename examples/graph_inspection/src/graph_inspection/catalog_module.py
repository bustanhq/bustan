"""Catalog feature module for the graph inspection example."""

from bustan import Module

from .catalog_controller import CatalogController
from .catalog_service import CatalogService


@Module(
    controllers=[CatalogController],
    providers=[CatalogService],
    exports=[CatalogService],
)
class CatalogModule:
    pass