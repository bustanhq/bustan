"""The caches and the ambient state one resolution runs against.

The one thing worth stating twice: a cache getter answers ``CACHE_MISS`` when a slot
is empty and never ``None``, because ``None`` is a value a provider may legitimately
produce and a probe that cannot tell the two apart rebuilds that provider forever.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, cast

import anyio
import pytest

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


def test_a_construction_lock_serializes_two_callers_and_is_forgotten_when_they_leave() -> None:
    # The lock table counts constructions in flight rather than every key ever built,
    # so a caller who chooses the key cannot grow it. The waiter is what makes the
    # release delicate: it is already holding the entry it is blocked on, so dropping
    # that entry while it waits would let the next caller build a second lock for the
    # same key and the two would construct the same instance at the same time.
    manager = ScopeManager()
    key = (AppModule, Service)
    order: list[str] = []
    holding = threading.Event()
    may_finish = threading.Event()

    def hold() -> None:
        with manager.get_construction_lock(key):
            order.append("holder in")
            holding.set()
            may_finish.wait(timeout=5)
            order.append("holder out")

    def wait() -> None:
        with manager.get_construction_lock(key):
            order.append("waiter in")

    holder = threading.Thread(target=hold)
    waiter = threading.Thread(target=wait)
    holder.start()
    assert holding.wait(timeout=5)
    assert len(manager.construction_locks) == 1

    waiter.start()
    waiter.join(timeout=0.2)

    assert order == ["holder in"]

    may_finish.set()
    holder.join(timeout=5)
    waiter.join(timeout=5)

    assert order == ["holder in", "holder out", "waiter in"]
    assert len(manager.construction_locks) == 0


def test_two_keys_are_built_under_locks_of_their_own() -> None:
    manager = ScopeManager()
    entered = threading.Event()

    with manager.get_construction_lock((AppModule, Service)):
        other = threading.Thread(target=lambda: _enter_and_signal(manager, "other", entered))
        other.start()

        assert entered.wait(timeout=5)

        other.join(timeout=5)

    assert len(manager.construction_locks) == 0


def _enter_and_signal(manager: ScopeManager, key: object, entered: threading.Event) -> None:
    """Take a construction lock and report having taken it."""

    with manager.get_construction_lock(key):
        entered.set()


def test_an_awaited_construction_lock_serializes_two_tasks_and_leaves_no_entry_behind() -> None:
    manager = ScopeManager()
    key = (AppModule, Service)
    order: list[str] = []

    async def build(name: str) -> None:
        async with manager.get_async_construction_lock(key):
            order.append(f"{name} in")
            # A checkpoint the other task would run at if the lock did not exclude it.
            await anyio.sleep(0)
            order.append(f"{name} out")

    async def contend() -> None:
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(build, "first")
            tasks.start_soon(build, "second")

    anyio.run(contend)

    assert order == ["first in", "first out", "second in", "second out"]
    assert len(manager.async_construction_locks) == 0


def test_the_durable_store_is_bounded_and_drops_the_partition_used_longest_ago() -> None:
    # A durable key is derived from the request, so whoever sends the request decides
    # how many partitions exist. The store holds its limit and no more.
    manager = ScopeManager(durable_instance_limit=2)
    first = (AppModule, Service, "tenant-a")
    second = (AppModule, Service, "tenant-b")
    third = (AppModule, Service, "tenant-c")

    manager.set_durable(first, "a")
    manager.set_durable(second, "b")
    # Reading a partition is a use of it, so the one dropped below is the one that has
    # gone longest without either a read or a write.
    assert manager.get_durable(first) == "a"

    manager.set_durable(third, "c")

    assert len(manager.durable_instances) == 2
    assert manager.get_durable(second) is CACHE_MISS
    assert manager.get_durable(first) == "a"
    assert manager.get_durable(third) == "c"


def test_a_durable_store_that_could_hold_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one entry"):
        ScopeManager(durable_instance_limit=0)


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


def test_the_durable_store_answers_the_whole_mapping_protocol_it_is_read_through() -> None:
    # Durable instances are read and written through a plain mapping, so the bounded
    # store has to answer the whole of that protocol and not only the two calls a
    # cache probe happens to make today.
    manager = ScopeManager()
    key = (AppModule, Service, "tenant-a")
    manager.set_durable(key, "a")

    assert list(manager.durable_instances) == [key]
    assert dict(manager.durable_instances) == {key: "a"}

    del manager.durable_instances[key]

    assert manager.get_durable(key) is CACHE_MISS
