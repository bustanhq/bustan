"""Shared setup for the tutorial application's tests.

One fixture builds the application and hands back a client already inside its lifespan,
so every test starts from an application that has run its bootstrap hooks and will run
its teardown ones. Without this each test would repeat six lines and one of them would
eventually forget to close.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from tutorial_app import build_application

from bustan.testing import AsgiTestClient

TOKEN = {"authorization": "Bearer tutorial-secret-token"}


@pytest.fixture
def client() -> Iterator[AsgiTestClient]:
    """An authenticated-capable client against a freshly built application."""
    with AsgiTestClient(build_application()) as running_client:
        yield running_client


@pytest.fixture
def token() -> dict[str, str]:
    """The header a caller sends to get past the policy guard."""
    return dict(TOKEN)
