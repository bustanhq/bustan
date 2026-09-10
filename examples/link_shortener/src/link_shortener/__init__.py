"""A link shortener: the application the Bustan tutorial series builds."""

from __future__ import annotations

import asyncio

import uvicorn

from bustan import Application, DocumentBuilder, SwaggerOptions, create_app
from bustan.testing import AsgiTestClient

from .app_module import AppModule


def build_application() -> Application:
    document = (
        DocumentBuilder()
        .set_title("Link Shortener")
        .set_description("Shorten a URL, then follow the short code.")
        .set_version("1.0.0")
        .add_bearer_auth()
    )
    # The redirect controller owns "/{code}", which shadows every single-segment path,
    # so the document lives two segments deep where the catch-all cannot reach it.
    return create_app(
        AppModule,
        swagger=SwaggerOptions(
            document_builder=document, path="/docs/api", swagger_ui_path="/docs/ui"
        ),
    )


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

    uvicorn.run("link_shortener:build_application", factory=True, port=3000, reload=True)


def demo() -> None:
    """Drive the finished application the way the tutorials tell a reader to."""

    application = build_application()
    token = {"authorization": "Bearer tutorial-secret-token"}
    with AsgiTestClient(application) as client:
        print("readiness     :", client.get("/health/ready").json())
        print(
            "no token      :",
            client.post("/links/", json={"url": "https://example.com"}).status_code,
        )

        created = client.post(
            "/links/", headers=token, json={"url": "https://bustan.dev/docs", "code": "docs"}
        )
        print("created       :", created.status_code, created.json())

        followed = client.get("/docs", follow_redirects=False)
        print("followed      :", followed.status_code, followed.headers.get("location"))

        print("read back     :", client.get("/links/docs", headers=token).json())
        print("unknown code  :", client.get("/nope", follow_redirects=False).status_code)
        print(
            "code taken    :",
            client.post(
                "/links/", headers=token, json={"url": "https://example.com", "code": "docs"}
            ).status_code,
        )

        bad = client.post("/links/", headers=token, json={"url": "not-a-url"})
        print("bad url       :", bad.status_code, bad.json()["errors"][0]["source"])
