"""The neutral names re-exported from the HTTP layer stay the contracts themselves.

Twelve modules in the package and eight test modules still import these names from
``bustan.platform.http.abstractions``. They keep working because the shim re-exports
the same objects rather than defining lookalikes, and an ``is`` comparison is the only
assertion that proves that.
"""

from __future__ import annotations

from bustan import contracts
from bustan.platform.http import abstractions

REEXPORTED_NAMES = (
    "HttpClientInfo",
    "HttpFileResponse",
    "HttpFormData",
    "HttpQueryParams",
    "HttpRequest",
    "HttpResponse",
    "HttpStreamResponse",
    "HttpUrl",
)

# The Starlette-flavoured names stay in the HTTP layer; the contracts package must not
# have grown them, or it would have grown a web framework dependency with them.
STARLETTE_FLAVOURED_NAMES = (
    "StarletteHttpRequest",
    "as_http_request",
    "to_starlette_response",
)


def test_every_reexported_name_is_the_contract_object() -> None:
    for name in REEXPORTED_NAMES:
        assert getattr(abstractions, name) is getattr(contracts, name), name


def test_the_reexported_names_stay_in_the_module_export_list() -> None:
    assert set(REEXPORTED_NAMES) <= set(abstractions.__all__)


def test_the_contracts_package_exports_what_it_defines() -> None:
    assert contracts.__all__ == (
        "HttpClientInfo",
        "HttpFileResponse",
        "HttpFormData",
        "HttpQueryParams",
        "HttpRequest",
        "HttpRequestState",
        "HttpResponse",
        "HttpStreamResponse",
        "HttpUrl",
        "QueryParams",
        "Url",
    )


def test_transport_specific_helpers_did_not_move_into_the_contracts() -> None:
    for name in STARLETTE_FLAVOURED_NAMES:
        assert hasattr(abstractions, name), name
        assert not hasattr(contracts, name), name
