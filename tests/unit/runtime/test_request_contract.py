"""The request contract must be satisfiable without any transport at all."""

from __future__ import annotations

import anyio

from bustan.contracts import HttpRequest, HttpResponse, RequestSlots


def test_a_neutral_response_carries_status_headers_and_body() -> None:
    response = HttpResponse.json({"status": "ok"}, status_code=201)
    response.headers["x-test"] = "present"
    response.set_body("updated")

    assert response.status_code == 201
    assert response.headers["x-test"] == "present"
    assert response.body == b"updated"


def test_http_request_protocol_accepts_non_starlette_url_query_and_form_shapes() -> None:
    request: HttpRequest = _AdapterNeutralRequest()

    assert request.url.path == "/users"
    assert request.query_params["active"] == "true"
    assert request.query_params.getlist("active") == ["true"]
    assert anyio.run(request.form).get("avatar") == "ada.png"


class _AdapterNeutralUrl:
    path = "/users"


class _AdapterNeutralQueryParams:
    def __contains__(self, key: object) -> bool:
        return key == "active"

    def __getitem__(self, key: str) -> str:
        if key != "active":
            raise KeyError(key)
        return "true"

    def getlist(self, key: str) -> list[str]:
        return ["true"] if key == "active" else []


class _AdapterNeutralFormData:
    def get(self, key: str, default: object | None = None) -> object | None:
        if key == "avatar":
            return "ada.png"
        return default

    def getlist(self, key: str) -> list[object]:
        value = self.get(key)
        return [] if value is None else [value]


class _AdapterNeutralRequest:
    native_request = object()
    method = "GET"
    path = "/users"
    url = _AdapterNeutralUrl()
    headers = {"host": "testserver"}
    query_params = _AdapterNeutralQueryParams()
    path_params: dict[str, str] = {}
    cookies: dict[str, str] = {}
    state = object()
    slots = RequestSlots()
    client = None
    app = object()

    async def body(self) -> bytes:
        return b""

    async def json(self) -> object:
        return {}

    async def form(self) -> _AdapterNeutralFormData:
        return _AdapterNeutralFormData()
