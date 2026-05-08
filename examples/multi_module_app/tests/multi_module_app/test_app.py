from starlette.testclient import TestClient

from multi_module_app import build_application


def test_multi_module_app_exposes_users_with_auth_issuer() -> None:
    application = build_application()

    with TestClient(application) as client:
        response = client.get("/users")

    assert response.status_code == 200
    assert response.json() == {
        "issuer": "bustan-auth",
        "users": [{"name": "Moses"}, {"name": "Ada"}],
    }