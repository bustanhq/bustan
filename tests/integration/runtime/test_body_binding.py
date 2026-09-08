"""Integration tests for binding a request body and for the document served when it does not fit."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import pytest

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


@dataclass(frozen=True, slots=True)
class Stamp:
    depth: int


@dataclass(frozen=True, slots=True)
class Record:
    ratio: float
    tags: list[str] = field(default_factory=list)
    stamp: Stamp | None = None


@Controller("/records")
class RecordsController:
    @Post("/")
    def create(self, payload: Record) -> dict[str, object]:
        return {
            "ratio": type(payload.ratio).__name__,
            "tags": list(payload.tags),
            "stamp": type(payload.stamp).__name__,
        }


@Module(controllers=[RecordsController])
class RecordsModule:
    pass


@dataclass(frozen=True, slots=True)
class Reading:
    count: int


def _reading_module(validation_mode: str) -> type[object]:
    """Build the same route over one validation mode, so the three can be compared."""

    @Controller("/readings", validation_mode=validation_mode)
    class ReadingsController:
        @Post("/")
        def create(self, payload: Reading) -> dict[str, object]:
            return {"count": type(payload.count).__name__}

    @Module(controllers=[ReadingsController])
    class ReadingsModule:
        pass

    return ReadingsModule


@Controller("/counters")
class CountersController:
    @Post("/")
    def create(self, count: int) -> dict[str, object]:
        return {"count": type(count).__name__}


@Module(controllers=[CountersController])
class CountersModule:
    pass


def _post(body: dict[str, object]) -> tuple[int, dict[str, object]]:
    with AsgiTestClient(cast(Any, create_app(NotesModule))) as client:
        response = client.post("/notes", json=body)
    return response.status_code, cast(dict[str, object], response.json())


def _post_to(module: type[object], path: str, body: object) -> tuple[int, dict[str, object]]:
    with AsgiTestClient(cast(Any, create_app(module))) as client:
        response = client.post(path, json=body)
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


_WRONG_COUNT_DETAIL = (
    "Could not bind request body 'payload' to Note: field of the wrong type 'count' (wanted int)"
)


@pytest.mark.parametrize(
    "value",
    ["abc", "7", [1, 2], None],
    ids=["a string", "a numeric string", "a list", "null"],
)
def test_a_body_field_that_is_not_its_declared_type_never_reaches_the_handler(
    value: object,
) -> None:
    """A handler annotated ``int`` is entitled to an ``int``, so nothing else is passed.

    A numeric string is refused with the rest rather than read as the number it spells.
    A query parameter arrives as text and has no other representation, so reading '7'
    as 7 is the only thing to do there; a JSON document carries numbers, so a caller
    that had 7 and sent '7' made a mistake worth being told about.
    """

    status_code, document = _post({"title": "Ada", "count": value})

    assert status_code == 400
    assert document["detail"] == _WRONG_COUNT_DETAIL
    assert document["reason"] == "field of the wrong type: count wanted int"


def test_a_body_field_that_is_its_declared_type_is_bound_and_served_by_the_handler() -> None:
    status_code, document = _post({"title": "Ada", "count": 3})

    assert status_code == 200
    assert document == {"title": "Ada", "count": 3}


def test_a_boolean_is_not_the_integer_it_is_a_subclass_of() -> None:
    """``bool`` subclasses ``int`` in Python, and a body that carried true carried no number.

    Refusing it is what a path or a query parameter declared ``int`` already does, and
    the alternative would let ``true`` arrive at arithmetic as the number one.
    """

    status_code, document = _post({"title": "Ada", "count": True})

    assert status_code == 400
    assert document["detail"] == _WRONG_COUNT_DETAIL


def test_a_body_missing_a_field_carrying_a_surplus_key_and_a_wrong_type_is_answered_once() -> None:
    """Three kinds of problem in one body are three clauses of one sentence.

    A caller holding all three repairs the body in one round trip rather than three.
    """

    status_code, document = _post({"count": "7", "colour": "red"})

    assert status_code == 400
    assert document["detail"] == (
        "Could not bind request body 'payload' to Note: missing required field 'title', "
        "unexpected field 'colour' and field of the wrong type 'count' (wanted int)"
    )
    assert document["reason"] == (
        "missing required field: title; unexpected field: colour; "
        "field of the wrong type: count wanted int"
    )


@pytest.mark.parametrize("validation_mode", ["auto", "explicit", "off"])
def test_every_validation_mode_binds_the_body_to_the_declared_types(validation_mode: str) -> None:
    """Binding is not validation, so switching validation off does not switch binding off.

    Path and query parameters are already bound whatever the mode says, and the body
    now matches them. This is asserted for all three members deliberately: a security
    property a configuration value can disable is one that gets disabled by accident.
    """

    module = _reading_module(validation_mode)

    refused_status, refused = _post_to(module, "/readings", {"count": "7"})
    accepted_status, accepted = _post_to(module, "/readings", {"count": 7})

    assert refused_status == 400
    assert refused["detail"] == (
        "Could not bind request body 'payload' to Reading: "
        "field of the wrong type 'count' (wanted int)"
    )
    assert accepted_status == 200
    assert accepted == {"count": "int"}


def test_a_body_bound_straight_to_a_scalar_parameter_holds_its_declared_type() -> None:
    """A field bound to a parameter is bound the same way as a field of a body model."""

    refused_status, refused = _post_to(CountersModule, "/counters", {"count": "7"})
    accepted_status, accepted = _post_to(CountersModule, "/counters", {"count": 7})

    assert refused_status == 400
    assert refused["detail"] == "Could not bind request body 'count' to int"
    assert refused["reason"] == "int expected"
    assert accepted_status == 200
    assert accepted == {"count": "int"}


def test_a_nested_object_is_built_from_the_object_the_caller_sent_for_it() -> None:
    status_code, document = _post_to(
        RecordsModule, "/records", {"ratio": 1.5, "stamp": {"depth": 2}}
    )

    assert status_code == 200
    assert document == {"ratio": "float", "tags": [], "stamp": "Stamp"}


def test_a_wrong_type_inside_a_nested_object_is_named_where_it_sits() -> None:
    status_code, document = _post_to(
        RecordsModule, "/records", {"ratio": 1.5, "stamp": {"depth": "deep"}}
    )

    assert status_code == 400
    assert document["detail"] == (
        "Could not bind request body 'payload' to Record: "
        "field of the wrong type 'stamp.depth' (wanted int)"
    )


def test_a_nested_object_of_the_wrong_shape_is_named_where_it_sits() -> None:
    status_code, document = _post_to(
        RecordsModule, "/records", {"ratio": 1.5, "stamp": {"colour": "red"}}
    )

    assert status_code == 400
    assert document["detail"] == (
        "Could not bind request body 'payload' to Record: "
        "missing required field 'stamp.depth' and unexpected field 'stamp.colour'"
    )


def test_a_wrong_type_inside_a_list_field_is_named_by_its_index() -> None:
    status_code, document = _post_to(RecordsModule, "/records", {"ratio": 1.5, "tags": ["red", 3]})

    assert status_code == 400
    assert document["detail"] == (
        "Could not bind request body 'payload' to Record: "
        "field of the wrong type 'tags[1]' (wanted str)"
    )


def test_a_scalar_where_a_list_is_declared_is_refused() -> None:
    status_code, document = _post_to(RecordsModule, "/records", {"ratio": 1.5, "tags": "red"})

    assert status_code == 400
    assert document["detail"] == (
        "Could not bind request body 'payload' to Record: "
        "field of the wrong type 'tags' (wanted list[str])"
    )


def test_an_integer_is_accepted_where_a_float_is_declared_and_is_left_alone() -> None:
    """A JSON document has one number literal, and an int is a float everywhere Python looks.

    Common encoders write 2.0 as 2, so refusing it would refuse bodies nobody wrote
    wrongly. It is passed on as it arrived rather than widened, because an integer
    beyond the range a float represents exactly would lose digits on the way through
    and the caller's own number is worth more than the name of its type.
    """

    status_code, document = _post_to(RecordsModule, "/records", {"ratio": 2})

    assert status_code == 200
    assert document == {"ratio": "int", "tags": [], "stamp": "NoneType"}
