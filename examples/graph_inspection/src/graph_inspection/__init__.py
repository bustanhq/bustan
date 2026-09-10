"""Graph inspection example package."""

from __future__ import annotations

import asyncio
import json

import uvicorn

from bustan import Application, DiscoveryService, create_app

from .app_module import AppModule
from .catalog_module import CatalogModule


def build_application() -> Application:
    return create_app(AppModule)


async def bootstrap() -> None:
    application = build_application()
    await application.listen(port=3000)


def main() -> None:
    asyncio.run(bootstrap())


def dev() -> None:
    """Serve with uvicorn's reloader watching this project.

    The application is named as an import string rather than built here, because the
    reloader restarts the process that serves it and so has to import the application
    for itself; a live object built in this process would not survive that restart.
    ``factory=True`` names the builder above, so a restarted worker builds exactly what
    every other entry point here builds.
    """

    uvicorn.run("graph_inspection:build_application", factory=True, port=3000, reload=True)


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
