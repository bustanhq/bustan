from starlette.testclient import TestClient

from blog_api import build_application


def test_blog_api_lists_seeded_posts() -> None:
    application = build_application()

    with TestClient(application) as client:
        response = client.get("/posts")

    assert response.status_code == 200
    assert response.json()[0]["title"] == "Shipping an alpha"


def test_blog_api_uses_request_actor_for_post_creation() -> None:
    application = build_application()

    with TestClient(application) as client:
        response = client.post(
            "/posts",
            headers={"x-user-id": "ada"},
            json={
                "title": "Request scoped author",
                "body": "Created through the example app.",
                "published": True,
            },
        )

    assert response.status_code == 200
    assert response.json()["created_by"] == "ada"