"""The application the Bustan tutorial series builds, at its end state."""

from __future__ import annotations

import asyncio

from bustan import Application, DocumentBuilder, SwaggerOptions, create_app
from bustan.testing import AsgiTestClient

from .app_module import AppModule


def build_application() -> Application:
    document = (
        DocumentBuilder()
        .set_title("Tutorial API")
        .set_description("The application the Bustan tutorial series builds.")
        .set_version("1.0.0")
        .add_bearer_auth()
    )
    return create_app(AppModule, swagger=SwaggerOptions(document_builder=document, path="/api"))


async def bootstrap(reload: bool = False) -> None:
    application = build_application()
    await application.listen(port=3000, reload=reload)


def main() -> None:
    asyncio.run(bootstrap())


def dev() -> None:
    asyncio.run(bootstrap(reload=True))


def demo() -> None:
    """Drive the finished application the way the tutorials tell a reader to."""

    application = build_application()
    token = {"authorization": "Bearer tutorial-secret-token"}
    with AsgiTestClient(application) as client:
        print("readiness    :", client.get("/health/ready").json())
        print("no token     :", client.get("/tasks/").status_code)
        created = client.post("/tasks/", headers=token, json={"title": "Read the tutorial"})
        print("created      :", created.status_code, created.json())
        print("listed       :", client.get("/tasks/", headers=token).json())
        print("missing task :", client.get("/tasks/999", headers=token).status_code)
        invalid = client.post("/tasks/", headers=token, json={"title": ""})
        print("invalid body :", invalid.status_code, invalid.json())
