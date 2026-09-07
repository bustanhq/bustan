from dynamic_module_usage import build_application

from bustan.testing import AsgiTestClient


def test_dynamic_module_example_returns_cached_value() -> None:
    application = build_application()

    with AsgiTestClient(application) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"cached_value": "prod:example-key"}
