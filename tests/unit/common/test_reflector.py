"""Unit tests for public metadata helpers."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from bustan import Reflector
from bustan.common.decorators.metadata import merge_metadata, override_metadata


@dataclass(frozen=True, slots=True)
class CacheControl:
    ttl: int


def test_reflector_get_all_and_override_prefers_handler_metadata() -> None:
    reflector = Reflector()
    cache_control = Reflector.create_decorator("cache_control")

    @cache_control(CacheControl(ttl=5))
    class UsersController:
        @cache_control(CacheControl(ttl=30))
        def list_users(self) -> None:
            return None

    metadata = reflector.get_all_and_override(
        cache_control,
        [UsersController.list_users, UsersController],
    )

    assert metadata == CacheControl(ttl=30)


def test_reflector_get_all_and_merge_preserves_declaration_order() -> None:
    reflector = Reflector()
    tags = Reflector.create_decorator("tags")

    @tags(("controller",))
    class UsersController:
        @tags(("handler",))
        def list_users(self) -> None:
            return None

    metadata = reflector.get_all_and_merge(tags, [UsersController, UsersController.list_users])

    assert metadata == ("controller", "handler")
    assert merge_metadata(("a",), ("b", "c")) == ("a", "b", "c")


def test_reflector_helpers_cover_missing_key_and_list_metadata_paths() -> None:
    reflector = Reflector()

    with pytest.raises(ValueError, match="cannot be empty"):
        Reflector.create_decorator("   ")

    roles = Reflector.create_decorator("roles")
    role_key = roles.key

    @roles(["admin", "editor"])
    class UsersController:
        def list_users(self) -> None:
            return None

    assert reflector.get(role_key, UsersController) == ["admin", "editor"]
    assert reflector.get_all_and_override(role_key, [UsersController.list_users]) is None
    assert reflector.get_all_and_merge(role_key, [UsersController]) == ("admin", "editor")
    assert override_metadata(None, "first", "second") == "first"
