from bustan import DiscoveryService

from graph_inspection import build_application


def test_graph_inspection_exposes_discovery_and_route_snapshot() -> None:
    application = build_application()
    discovery = application.get(DiscoveryService)

    modules = discovery.modules()
    routes = application.snapshot_routes()

    assert [entry["module"] for entry in modules] == ["AppModule", "CatalogModule", "DiscoveryModule"]
    assert [entry["path"] for entry in routes] == ["/catalog"]