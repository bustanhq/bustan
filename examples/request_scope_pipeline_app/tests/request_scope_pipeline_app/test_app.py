from starlette.testclient import TestClient

from request_scope_pipeline_app import build_application


def test_request_scope_pipeline_rejects_missing_identity() -> None:
    application = build_application()

    with TestClient(application) as client:
        response = client.get("/account/me")

    assert response.status_code == 403


def test_request_scope_pipeline_shares_request_identity_across_components() -> None:
    application = build_application()

    with TestClient(application) as client:
        response = client.get(
            "/account/me",
            headers={"x-user-id": "moses", "x-request-id": "req-42"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "request_id": "req-42",
        "user_id": "moses",
        "data": {
            "path": "/account/me",
            "user_id": "moses",
            "plan": "pro",
        },
    }