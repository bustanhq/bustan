"""The caches and the ambient state one resolution runs against.

The one thing worth stating twice: a cache getter answers ``CACHE_MISS`` when a slot
is empty and never ``None``, because ``None`` is a value a provider may legitimately
produce and a probe that cannot tell the two apart rebuilds that provider forever.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from bustan.core.ioc.scopes import (
    CACHE_MISS,
    REQUEST_SCOPE_CACHE_ATTR,
    REQUEST_SCOPE_CONTROLLER_CACHE_ATTR,
    ScopeManager,
)

if TYPE_CHECKING:
    from tests.conftest import RequestFactory


class AppModule:
    """A stand-in module key for the cache keys under test."""


class Service:
    """A stand-in token for the cache keys under test."""


def test_an_empty_slot_answers_cache_miss_and_a_cached_none_answers_none() -> None:
    manager = ScopeManager()
    singleton_key = (AppModule, Service)
    durable_key = (AppModule, Service, "tenant-a")

    assert manager.get_singleton(singleton_key) is CACHE_MISS
    assert manager.get_durable(durable_key) is CACHE_MISS

    manager.set_singleton(singleton_key, None)
    manager.set_durable(durable_key, None)

    assert manager.get_singleton(singleton_key) is None
    assert manager.get_durable(durable_key) is None


def test_the_cache_miss_marker_names_itself_in_a_diagnostic() -> None:
    assert repr(CACHE_MISS) == "CACHE_MISS"


def test_a_construction_lock_is_the_same_lock_every_time_it_is_asked_for() -> None:
    manager = ScopeManager()
    key = (AppModule, Service)

    assert manager.get_construction_lock(key) is manager.get_construction_lock(key)
    assert manager.get_construction_lock(key) is not manager.get_construction_lock("other")


def test_a_controller_singleton_lock_is_the_same_lock_every_time_it_is_asked_for() -> None:
    manager = ScopeManager()
    key = (AppModule, Service)

    assert manager.get_controller_singleton_lock(key) is manager.get_controller_singleton_lock(key)


def test_cached_controllers_are_dropped_when_an_override_is_registered() -> None:
    manager = ScopeManager()
    key = (AppModule, Service)
    manager.set_controller_singleton(key, "instance")

    assert manager.get_controller_singleton(key) == "instance"

    manager.clear_controller_singletons()

    assert manager.get_controller_singleton(key) is None


def test_ambient_state_is_restored_exactly_as_it_was_found() -> None:
    manager = ScopeManager()
    response = object()
    application = object()

    assert manager.push_response(None) is None
    assert manager.push_application(None) is None

    response_token = manager.push_response(response)
    application_token = manager.push_application(application)

    assert manager.active_response.get() is response
    assert manager.active_application.get() is application

    manager.pop_response(response_token)
    manager.pop_application(application_token)
    manager.pop_response(None)
    manager.pop_application(None)

    assert manager.active_response.get() is None
    assert manager.active_application.get() is None


def test_the_active_request_is_restored_exactly_as_it_was_found(
    build_request: RequestFactory,
) -> None:
    manager = ScopeManager()
    request = build_request(path="/items")

    assert manager.push_request(None) is None

    token = manager.push_request(request)

    assert manager.active_request.get() is request

    manager.pop_request(token)
    manager.pop_request(None)

    assert manager.active_request.get() is None


def test_a_request_carries_one_cache_which_is_dropped_when_the_request_ends(
    build_request: RequestFactory,
) -> None:
    manager = ScopeManager()
    request = build_request(path="/items")

    assert manager.get_request_cache(request) is manager.get_request_cache(request)
    assert manager.get_request_controller_cache(request) is manager.get_request_controller_cache(
        request
    )

    manager.clear_request_state(request)

    assert not hasattr(request.state, REQUEST_SCOPE_CACHE_ATTR)
    assert not hasattr(request.state, REQUEST_SCOPE_CONTROLLER_CACHE_ATTR)


def test_clearing_the_state_of_something_without_any_is_not_an_error() -> None:
    manager = ScopeManager()

    manager.clear_request_state(None)


def test_clearing_the_state_of_something_that_carries_none_is_not_an_error() -> None:
    class Stateless:
        state = None

    ScopeManager().clear_request_state(cast(Any, Stateless()))
