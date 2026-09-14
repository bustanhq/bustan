"""Unit tests for handler response coercion."""

from __future__ import annotations

import datetime
import decimal
import enum
import json
import math
import uuid
from collections import OrderedDict
from dataclasses import asdict, dataclass

import pytest
from starlette.responses import PlainTextResponse

from bustan.contracts import HttpResponse
from bustan.runtime.responses import coerce_response


def _dumps(value: object) -> bytes:
    """Return the body ``HttpResponse.json`` writes for ``value``."""

    return json.dumps(value, separators=(",", ":")).encode("utf-8")


class Colour(enum.StrEnum):
    RED = "red"


class Priority(enum.IntEnum):
    HIGH = 3


class Permission(enum.IntFlag):
    READ = 1
    WRITE = 2


class Weekday(enum.Enum):
    MONDAY = "monday"


class Label(str):
    pass


@dataclass(frozen=True, slots=True)
class Point:
    x: int
    y: int


def test_coerce_response_passes_a_transport_built_response_through_untouched() -> None:
    response = PlainTextResponse("ok", status_code=201)

    assert coerce_response(response) is response


def test_coerce_response_serializes_dict_and_list_values() -> None:
    dict_response = coerce_response({"status": "ok"})
    list_response = coerce_response(["bustan", "lette"])

    assert isinstance(dict_response, HttpResponse)
    assert isinstance(list_response, HttpResponse)
    assert dict_response.body == b'{"status":"ok"}'
    assert list_response.body == b'["bustan","lette"]'


def test_coerce_response_serializes_dataclass_instances() -> None:
    @dataclass(frozen=True, slots=True)
    class Payload:
        status: str
        count: int

    response = coerce_response(Payload(status="ok", count=2))

    assert isinstance(response, HttpResponse)
    assert response.body == b'{"status":"ok","count":2}'


def test_coerce_response_converts_none_to_no_content() -> None:
    response = coerce_response(None)

    assert isinstance(response, HttpResponse)
    assert response.status_code == 204
    assert response.body == b""


def test_coerce_response_rejects_unsupported_values() -> None:
    with pytest.raises(TypeError, match="Unsupported handler return type"):
        coerce_response("ok")


_NOT_ASCII_NAME = "Zo\N{LATIN SMALL LETTER E WITH DIAERESIS}"


# Values whose body is the one json.dumps writes, whichever encoder wrote it: msgspec writes
# the same text for some, and for the rest it raises or writes a character json.dumps
# escapes, so json.dumps writes the body.
_WRITTEN_AS_JSON_DUMPS_WRITES: dict[str, object] = {
    "text that is not ASCII": {"name": _NOT_ASCII_NAME, "greeting": "\N{WAVING HAND SIGN}"},
    "U+2028 and U+2029": [
        "line\N{LINE SEPARATOR}separator",
        "paragraph\N{PARAGRAPH SEPARATOR}separator",
    ],
    "control characters": ["".join(map(chr, range(0x20))) + "\x7f"],
    "a lone surrogate": ["\ud800"],
    "large integers": [2**63 - 1, 2**64, -(2**63) - 1, 10**30, -(10**30)],
    "bool and None keys": {True: "yes", False: "no", None: "unknown"},
    "int and float keys": {1: "one", -2: "minus two", 0.5: "a half"},
    "enums": [Colour.RED, Priority.HIGH, Permission.READ | Permission.WRITE],
    "enum keys": {Colour.RED: 1, Priority.HIGH: 2},
    "a str subclass": [Label("label")],
    "a str subclass key": {Label("label"): 1},
    "floats msgspec spells as json.dumps does": [0.0, -0.0, 0.1, 1e15, 0.0001, 1e-10],
    "nested containers": {"items": [{"id": 1, "tags": ("a", "b")}], "empty": {}},
    "NaN beside text that is not ASCII": {"name": _NOT_ASCII_NAME, "ratio": math.nan},
}


@pytest.mark.parametrize(
    "value",
    list(_WRITTEN_AS_JSON_DUMPS_WRITES.values()),
    ids=list(_WRITTEN_AS_JSON_DUMPS_WRITES),
)
def test_coerce_response_writes_the_bytes_json_dumps_writes(value: object) -> None:
    response = coerce_response(value)

    assert isinstance(response, HttpResponse)
    assert response.body == _dumps(value)


def test_coerce_response_writes_a_dataclass_as_json_dumps_writes_its_fields() -> None:
    @dataclass(frozen=True, slots=True)
    class Shipment:
        origin: Point
        crates: int
        note: str

    for shipment in (
        Shipment(origin=Point(1, 2), crates=2**64, note="plain"),
        Shipment(origin=Point(3, 4), crates=1, note="caf\N{LATIN SMALL LETTER E WITH ACUTE}\x7f"),
    ):
        response = coerce_response(shipment)

        assert isinstance(response, HttpResponse)
        assert response.body == _dumps(asdict(shipment))


def test_coerce_response_writes_non_finite_floats_as_null_and_exponents_unpadded() -> None:
    value = [math.nan, math.inf, -math.inf, 1e16, -2.5e300, 1e-7]

    response = coerce_response(value)

    assert isinstance(response, HttpResponse)
    assert _dumps(value) == b"[NaN,Infinity,-Infinity,1e+16,-2.5e+300,1e-07]"
    assert response.body == b"[null,null,null,1e16,-2.5e300,1e-7]"


def test_coerce_response_writes_small_floats_non_finite_keys_and_containers_as_stored() -> None:
    reordered = OrderedDict(first=1, second=2)
    reordered.move_to_end("first")
    value = {"ratio": 1.5e-5, "keyed": {math.inf: 1, math.nan: 2}, "reordered": reordered}

    response = coerce_response(value)

    assert isinstance(response, HttpResponse)
    assert _dumps(value) == (
        b'{"ratio":1.5e-05,"keyed":{"Infinity":1,"NaN":2},"reordered":{"second":2,"first":1}}'
    )
    assert response.body == (
        b'{"ratio":0.000015,"keyed":{"inf":1,"nan":2},"reordered":{"first":1,"second":2}}'
    )


@pytest.mark.parametrize(
    ("value", "body"),
    [
        (
            [datetime.datetime(2026, 9, 14, 12, 30, tzinfo=datetime.UTC)],
            b'["2026-09-14T12:30:00Z"]',
        ),
        ([datetime.date(2026, 9, 14)], b'["2026-09-14"]'),
        ([datetime.time(12, 30)], b'["12:30:00"]'),
        ([datetime.timedelta(days=1, seconds=5)], b'["P1DT5S"]'),
        ([uuid.UUID(int=1)], b'["00000000-0000-0000-0000-000000000001"]'),
        ([decimal.Decimal("1.50")], b'["1.50"]'),
        ([b"ab"], b'["YWI="]'),
        ([{1}, frozenset({2})], b"[[1],[2]]"),
        ([Weekday.MONDAY], b'["monday"]'),
        ([Point(1, 2)], b'[{"x":1,"y":2}]'),
        ({uuid.UUID(int=1): "first"}, b'{"00000000-0000-0000-0000-000000000001":"first"}'),
    ],
    ids=[
        "datetime",
        "date",
        "time",
        "timedelta",
        "UUID",
        "Decimal",
        "bytes",
        "set and frozenset",
        "Enum without a mixin",
        "dataclass inside a list",
        "UUID key",
    ],
)
def test_coerce_response_encodes_values_json_dumps_refuses(value: object, body: bytes) -> None:
    with pytest.raises(TypeError):
        _dumps(value)

    response = coerce_response(value)

    assert isinstance(response, HttpResponse)
    assert response.body == body


def test_coerce_response_builds_the_response_http_response_json_builds() -> None:
    value = {"status": "ok", "count": 2}

    response = coerce_response(value)
    expected = HttpResponse.json(value)

    assert isinstance(response, HttpResponse)
    assert response.status_code == expected.status_code == 200
    assert response.headers == expected.headers == {}
    assert response.media_type == expected.media_type == "application/json"
    assert response.body == expected.body
    assert response.headers is not coerce_response(value).headers


def test_a_response_built_with_http_response_json_keeps_the_bytes_json_dumps_writes() -> None:
    response = HttpResponse.json([math.nan, 1e16, 1.5e-5, "\x7f"])

    assert coerce_response(response) is response
    assert response.body == b'[NaN,1e+16,1.5e-05,"\\u007f"]'
