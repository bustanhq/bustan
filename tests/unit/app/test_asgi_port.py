"""The application the framework builds must satisfy the ASGI port it is passed to.

Every assertion here is deliberately written without a cast. The framework hands the
same object to a server and to the in-process client, so if ``Application`` stops being
assignable to ``AsgiApp`` this module fails under the type checker rather than at
runtime, where the composition has always worked.
"""

from __future__ import annotations

from bustan import Controller, Get, Module
from bustan.adapters.asgi.types import AsgiApp
from bustan.testing import AsgiTestClient, create_test_app


@Controller("/port")
class PortController:
    @Get("/probe")
    def read_probe(self) -> dict[str, str]:
        return {"status": "ok"}


@Module(controllers=[PortController])
class PortModule:
    pass


def _serve(app: AsgiApp) -> AsgiApp:
    """Accept anything a server may drive, and hand it back unchanged.

    The parameter annotation is the assertion: a caller passing something that is not
    an ASGI application is a type error, so this stands in for the server that would
    otherwise have to be started to make the same claim.
    """

    return app


def test_application_is_assignable_to_the_asgi_port() -> None:
    application = create_test_app(PortModule)

    assert _serve(application) is application


def test_test_client_accepts_the_application_the_framework_builds() -> None:
    with AsgiTestClient(create_test_app(PortModule)) as client:
        response = client.get("/port/probe")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
