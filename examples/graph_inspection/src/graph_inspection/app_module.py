"""Root module for the graph inspection example."""

from bustan import DiscoveryModule, Module

from .catalog_module import CatalogModule


@Module(imports=[CatalogModule, DiscoveryModule])
class AppModule:
    pass