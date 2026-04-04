"""Example showing how to inspect the discovered module graph."""

from star import controller, create_app, get, injectable, module


@injectable
class CatalogService:
    def list_categories(self) -> list[str]:
        return ["frameworks", "testing", "tooling"]


@controller("/catalog")
class CatalogController:
    def __init__(self, catalog_service: CatalogService) -> None:
        self.catalog_service = catalog_service

    @get("/")
    def list_categories(self) -> list[str]:
        return self.catalog_service.list_categories()


@module(
    controllers=[CatalogController],
    providers=[CatalogService],
    exports=[CatalogService],
)
class CatalogModule:
    pass


@module(imports=[CatalogModule])
class AppModule:
    pass


app = create_app(AppModule)


def describe_graph() -> None:
    """Print the imported modules and exported providers for each node."""

    graph = app.state.star_module_graph
    for node in graph.nodes:
        imported_module_names = [imported_module.__name__ for imported_module in node.imports]
        exported_provider_names = [provider.__name__ for provider in node.exported_providers]
        print(f"{node.module.__name__}: imports={imported_module_names}, exports={exported_provider_names}")


if __name__ == "__main__":
    describe_graph()