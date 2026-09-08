"""Integration tests for the document served when a request body does not fit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from bustan import Controller, Module, Post, create_app
from bustan.testing import AsgiTestClient


@dataclass(frozen=True, slots=True)
class Note:
    title: str
    count: int
    enabled: bool = True


@Controller("/notes")
class NotesController:
    @Post("/")
    def create(self, payload: Note) -> dict[str, object]:
        return {"title": payload.title, "count": payload.count}


@Module(controllers=[NotesController])
class NotesModule:
    pass


def _post(body: dict[str, object]) -> tuple[int, dict[str, object]]:
    with AsgiTestClient(cast(Any, create_app(NotesModule))) as client:
        response = client.post("/notes", json=body)
    return response.status_code, cast(dict[str, object], response.json())


def test_a_body_missing_a_field_and_carrying_an_unknown_one_is_answered_once() -> None:
    """One round trip repairs the body, so both problems are named in one document."""

    status_code, document = _post({"title": "Ada", "colour": "red"})

    assert status_code == 400
    assert document == {
        "type": "about:blank",
        "title": "Bad Request",
        "status": 400,
        "detail": (
            "Could not bind request body 'payload' to Note: "
            "missing required field 'count' and unexpected field 'colour'"
        ),
        "instance": "/notes",
        "errors": [
            {
                "field": "payload",
                "source": "request body",
                "reason": "missing required field: count; unexpected field: colour",
            }
        ],
        "field": "payload",
        "source": "request body",
        "reason": "missing required field: count; unexpected field: colour",
    }


def test_a_body_carrying_only_an_unknown_key_is_answered_in_composed_words() -> None:
    """The served wording is the framework's own, naming no constructor and no argument."""

    status_code, document = _post({"title": "Ada", "count": 2, "colour": "red"})

    assert status_code == 400
    assert document == {
        "type": "about:blank",
        "title": "Bad Request",
        "status": 400,
        "detail": ("Could not bind request body 'payload' to Note: unexpected field 'colour'"),
        "instance": "/notes",
        "errors": [
            {
                "field": "payload",
                "source": "request body",
                "reason": "unexpected field: colour",
            }
        ],
        "field": "payload",
        "source": "request body",
        "reason": "unexpected field: colour",
    }

    served = repr(document)
    assert "__init__" not in served
    assert "keyword argument" not in served
    assert "positional argument" not in served


def test_a_body_missing_one_field_is_answered_as_it_was_before() -> None:
    status_code, document = _post({"title": "Ada"})

    assert status_code == 400
    assert document["detail"] == (
        "Could not bind request body 'payload' to Note: missing required field 'count'"
    )
    assert document["reason"] == "missing required field: count"


def test_a_body_missing_several_fields_is_answered_as_it_was_before() -> None:
    status_code, document = _post({})

    assert status_code == 400
    assert document["detail"] == (
        "Could not bind request body 'payload' to Note: missing required fields 'title', 'count'"
    )
    assert document["reason"] == "missing required fields: title, count"


def test_a_body_that_fits_is_bound_and_served_by_the_handler() -> None:
    status_code, document = _post({"title": "Ada", "count": 2})

    assert status_code == 200
    assert document == {"title": "Ada", "count": 2}
