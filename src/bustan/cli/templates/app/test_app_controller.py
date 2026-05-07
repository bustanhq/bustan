from starlette.testclient import TestClient

from bustan.testing import create_test_app

from $package_name.app_module import AppModule


def test_get_message_returns_200_with_expected_payload() -> None:
    app = create_test_app(AppModule)
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello from $project_name"}
