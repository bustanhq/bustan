"""One test per promise the tutorial series makes.

Each name is the sentence its tutorial ends on. They keep passing as later tutorials add
layers, which is what stops the series drifting from the code it describes.
"""

from __future__ import annotations

from bustan.testing import AsgiTestClient


def test_shortening_a_url_returns_201(client: AsgiTestClient, token: dict[str, str]) -> None:
    response = client.post("/links/", headers=token, json={"url": "https://example.com/a"})
    assert response.status_code == 201
    assert response.headers["location"] == f"/links/{response.json()['code']}"


def test_following_a_code_redirects_to_the_target(
    client: AsgiTestClient, token: dict[str, str]
) -> None:
    client.post("/links/", headers=token, json={"url": "https://example.com/b", "code": "bee"})
    response = client.get("/bee", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "https://example.com/b"


def test_following_a_code_counts_the_visit(client: AsgiTestClient, token: dict[str, str]) -> None:
    client.post("/links/", headers=token, json={"url": "https://example.com/c", "code": "see"})
    client.get("/see", follow_redirects=False)
    assert client.get("/links/see", headers=token).json()["visits"] == 1


def test_an_unknown_code_returns_404(client: AsgiTestClient) -> None:
    response = client.get("/nothing-here", follow_redirects=False)
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "not-found"


def test_a_taken_code_returns_409(client: AsgiTestClient, token: dict[str, str]) -> None:
    body = {"url": "https://example.com/d", "code": "twice"}
    client.post("/links/", headers=token, json=body)
    assert client.post("/links/", headers=token, json=body).status_code == 409


def test_a_malformed_url_returns_problem_details(
    client: AsgiTestClient, token: dict[str, str]
) -> None:
    response = client.post("/links/", headers=token, json={"url": "not-a-url"})
    assert response.status_code == 400
    assert response.json()["errors"][0]["source"] == "body"


def test_creating_a_link_needs_a_token(client: AsgiTestClient) -> None:
    assert client.post("/links/", json={"url": "https://example.com/e"}).status_code == 401


def test_following_a_link_needs_no_token(client: AsgiTestClient, token: dict[str, str]) -> None:
    """A short link nobody can click is not a short link."""
    client.post("/links/", headers=token, json={"url": "https://example.com/f", "code": "open"})
    assert client.get("/open", follow_redirects=False).status_code == 302


def test_every_response_carries_a_request_id(client: AsgiTestClient, token: dict[str, str]) -> None:
    assert client.get("/links/", headers=token).headers["x-request-id"]


def test_the_probes_are_not_stamped(client: AsgiTestClient) -> None:
    assert "x-request-id" not in client.get("/health/live").headers


def test_readiness_reports_the_store(client: AsgiTestClient) -> None:
    assert client.get("/health/ready").json()["checks"]["link-store"]["status"] == "up"


def test_the_openapi_document_is_served(client: AsgiTestClient) -> None:
    document = client.get("/docs/api").json()
    assert document["info"]["title"] == "Link Shortener"
    assert "/links" in document["paths"]
