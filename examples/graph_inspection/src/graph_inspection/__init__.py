"""Graph inspection example package."""

from __future__ import annotations

import asyncio
import json

from bustan import Application, DiscoveryService, create_app

from .app_module import AppModule
from .catalog_module import CatalogModule


def build_application() -> Application:
    return create_app(AppModule)


async def bootstrap(reload: bool = False) -> None:
    application = build_application()
    await application.listen(port=3000, reload=reload)


def main() -> None:
    asyncio.run(bootstrap())


def dev() -> None:
    asyncio.run(bootstrap(reload=True))


def demo() -> None:
    """Print supported runtime inspection artifacts for the compiled app."""

    application = build_application()
    discovery = application.get(DiscoveryService)
    report = {
        "modules": discovery.modules(),
        "catalog_providers": discovery.providers_for_module(CatalogModule),
        "routes": application.snapshot_routes(),
    }
    print(json.dumps(report, indent=2))