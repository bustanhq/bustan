"""One test per promise the tutorial series makes.

Each name is the sentence its tutorial ends on. They keep passing as later tutorials add
layers, which is what stops the series drifting from the code it describes.
"""

from __future__ import annotations

from bustan.testing import AsgiTestClient


def test_create_returns_201(client: AsgiTestClient, token: dict[str, str]) -> None:
    response = client.post("/tasks/", headers=token, json={"title": "Write the tutorial"})
    assert response.status_code == 201
    assert response.headers["location"] == f"/tasks/{response.json()['id']}"


def test_a_created_task_is_listed(client: AsgiTestClient, token: dict[str, str]) -> None:
    client.post("/tasks/", headers=token, json={"title": "Read it back"})
    titles = [task["title"] for task in client.get("/tasks/", headers=token).json()]
    assert "Read it back" in titles


def test_missing_task_returns_404(client: AsgiTestClient, token: dict[str, str]) -> None:
    response = client.get("/tasks/999", headers=token)
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "not-found"


def test_invalid_payload_returns_problem_details(
    client: AsgiTestClient, token: dict[str, str]
) -> None:
    response = client.post("/tasks/", headers=token, json={"title": ""})
    assert response.status_code == 400
    body = response.json()
    assert body["errors"][0]["source"] == "body"


def test_a_request_without_a_token_is_refused(client: AsgiTestClient) -> None:
    assert client.get("/tasks/").status_code == 401


def test_every_response_carries_a_request_id(client: AsgiTestClient, token: dict[str, str]) -> None:
    response = client.get("/tasks/", headers=token)
    assert response.headers["x-request-id"]


def test_the_probes_are_not_stamped(client: AsgiTestClient) -> None:
    """The middleware excludes them, so their absence is the exclusion working."""
    assert "x-request-id" not in client.get("/health/live").headers


def test_readiness_reports_the_store(client: AsgiTestClient) -> None:
    checks = client.get("/health/ready").json()["checks"]
    assert checks["task-store"]["status"] == "up"


def test_the_openapi_document_is_served(client: AsgiTestClient) -> None:
    document = client.get("/api").json()
    assert document["info"]["title"] == "Tutorial API"
    assert "/tasks" in document["paths"]
    assert "/tasks/{task_id}" in document["paths"]
