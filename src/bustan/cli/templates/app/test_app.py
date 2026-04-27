from starlette.testclient import TestClient

from $package_name import app


def test_read_root() -> None:
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "Hello from $project_name"}
