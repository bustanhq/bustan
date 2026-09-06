"""Unit tests for the token identity rule shared by the markers and the registry."""

from __future__ import annotations

from enum import StrEnum

from bustan.common.tokens import token_identity


def test_token_identity_separates_equal_tokens_of_different_types() -> None:
    class Tokens(StrEnum):
        DB = "db"

    assert Tokens.DB == "db"
    assert hash(Tokens.DB) == hash("db")
    assert token_identity(Tokens.DB) != token_identity("db")
    assert token_identity(True) != token_identity(1)
    assert token_identity("db") == token_identity("db")
