"""Catalog service for the graph inspection example."""

from bustan import Injectable


@Injectable()
class CatalogService:
    def list_categories(self) -> list[str]:
        return ["frameworks", "testing", "tooling"]