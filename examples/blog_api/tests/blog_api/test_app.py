from blog_api import build_application

from bustan.testing import AsgiTestClient


def test_blog_api_lists_seeded_posts() -> None:
    application = build_application()

    with AsgiTestClient(application) as client:
        response = client.get("/posts")

    assert response.status_code == 200
    assert response.json()[0]["title"] == "Shipping an alpha"


def test_blog_api_uses_request_actor_for_post_creation() -> None:
    application = build_application()

    with AsgiTestClient(application) as client:
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


def test_blog_api_answers_404_for_a_post_that_does_not_exist() -> None:
    application = build_application()

    with AsgiTestClient(application) as client:
        response = client.get("/posts/999")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "not-found"
