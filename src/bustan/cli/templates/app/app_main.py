import asyncio

import uvicorn
from bustan import Application, create_app

from .app_module import AppModule

HOST = "127.0.0.1"
PORT = 3000


def create_asgi_app() -> Application:
    """Return the application, which is itself the ASGI callable a server runs."""
    return create_app(AppModule)


async def bootstrap() -> None:
    await create_asgi_app().listen(port=PORT, host=HOST)


def main() -> None:
    asyncio.run(bootstrap())


def dev() -> None:
    # Reloading means owning the process: the server watches the source tree and, on
    # every change, starts a worker that imports the application again. That is why it
    # is handed the name of a factory rather than an application already built - a
    # built one belongs to the process that built it, and could not be rebuilt here.
    uvicorn.run(
        "$package_name.app_main:create_asgi_app",
        factory=True,
        host=HOST,
        port=PORT,
        reload=True,
        reload_dirs=["src"],
    )
