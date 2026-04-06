"""Example showing how to inspect the discovered module graph."""

from typing import Any, cast
from bustan import Controller, create_app, Get, Injectable, Module


@Injectable
class CatalogService:
    def list_categories(self) -> list[str]:
        return ["frameworks", "testing", "tooling"]


@Controller("/catalog")
class CatalogController:
    def __init__(self, catalog_service: CatalogService) -> None:
        self.catalog_service = catalog_service

    @Get("/")
    def list_categories(self) -> list[str]:
        return self.catalog_service.list_categories()


@Module(
    controllers=[CatalogController],
    providers=[CatalogService],
    exports=[CatalogService],
)
class CatalogModule:
    pass


@Module(imports=[CatalogModule])
class AppModule:
    pass


app = create_app(AppModule)


def describe_graph() -> None:
    """Print the imported modules and exported providers for each node."""

    graph = cast(Any, app.module_graph)
    for node in graph.nodes:
        imported_module_names = [imported_module.__name__ for imported_module in node.imports]
        exported_provider_names = [provider.__name__ for provider in node.exported_providers]
        print(
            f"{node.module.__name__}: imports={imported_module_names}, exports={exported_provider_names}"
        )


if __name__ == "__main__":
    describe_graph()
