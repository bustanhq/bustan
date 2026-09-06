"""The caches and the ambient state one resolution runs against.

The one thing worth stating twice: a cache getter answers ``CACHE_MISS`` when a slot
is empty and never ``None``, because ``None`` is a value a provider may legitimately
produce and a probe that cannot tell the two apart rebuilds that provider forever.
"""

from __future__ import annotations

import threading
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

import anyio
import pytest

from bustan import Module
from bustan.kernel.ioc.container import build_container
from bustan.kernel.ioc.scopes import (
    CACHE_MISS,
    REQUEST_SCOPE_CACHE_ATTR,
    REQUEST_SCOPE_CONTROLLER_CACHE_ATTR,
    ScopeManager,
)
from bustan.kernel.module.graph import build_module_graph

if TYPE_CHECKING:
    from tests.conftest import HttpRequestFactory


class AppModule:
    """A stand-in module key for the cache keys under test."""


class Service:
    """A stand-in token for the cache keys under test."""


class Tokens(StrEnum):
    """A token whose members are equal to the bare strings they carry."""

    DB = "db"


class FromEnumToken:
    """What the module declaring the enum member provides."""


class FromStrToken:
    """What the module declaring the bare string provides."""


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
    build_http_request: HttpRequestFactory,
) -> None:
    manager = ScopeManager()
    request = build_http_request(path="/items")

    assert manager.push_request(None) is None

    token = manager.push_request(request)

    assert manager.active_request.get() is request

    manager.pop_request(token)
    manager.pop_request(None)

    assert manager.active_request.get() is None


def test_a_request_carries_one_cache_which_is_dropped_when_the_request_ends(
    build_http_request: HttpRequestFactory,
) -> None:
    manager = ScopeManager()
    request = build_http_request(path="/items")

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


def test_two_equal_tokens_of_different_types_keep_separate_singleton_slots() -> None:
    # A string enum member and the bare string it equals are two tokens, so they are
    # two bindings and need two slots. Keyed by equality alone the second write lands
    # on the first's slot and whoever asked for the string is handed the enum's
    # instance, which reads as a provider returning another provider's object.
    manager = ScopeManager()
    from_enum = FromEnumToken()
    from_str = FromStrToken()

    manager.set_singleton((AppModule, Tokens.DB), from_enum)
    manager.set_singleton((AppModule, "db"), from_str)

    assert manager.get_singleton((AppModule, Tokens.DB)) is from_enum
    assert manager.get_singleton((AppModule, "db")) is from_str
    assert len(manager.singletons) == 2


def test_a_true_token_and_a_one_token_keep_separate_singleton_slots() -> None:
    # ``True == 1`` and the two hash alike, so the same collapse reaches any pair of
    # equal values of different types, not only strings and string enums.
    manager = ScopeManager()
    from_true = FromEnumToken()
    from_one = FromStrToken()

    manager.set_singleton((AppModule, True), from_true)
    manager.set_singleton((AppModule, 1), from_one)

    assert manager.get_singleton((AppModule, True)) is from_true
    assert manager.get_singleton((AppModule, 1)) is from_one
    assert len(manager.singletons) == 2


def test_two_equal_tokens_of_different_types_keep_separate_request_scoped_slots(
    build_http_request: HttpRequestFactory,
) -> None:
    manager = ScopeManager()
    request = build_http_request(path="/items")
    cache = manager.get_request_cache(request)
    from_enum = FromEnumToken()
    from_str = FromStrToken()

    cache[(AppModule, Tokens.DB)] = from_enum
    cache[(AppModule, "db")] = from_str

    assert cache[(AppModule, Tokens.DB)] is from_enum
    assert cache[(AppModule, "db")] is from_str
    assert len(cache) == 2


def test_a_singleton_slot_is_read_back_under_the_key_it_was_written_with() -> None:
    # The override sweep and the lifecycle runner both walk the singleton table and
    # take the module and the token out of each key, so iteration has to give back the
    # key as its writer spelled it rather than the shape the table keys by.
    manager = ScopeManager()
    manager.set_singleton((AppModule, Tokens.DB), "from enum")
    manager.set_singleton((AppModule, "db"), "from str")

    assert list(manager.singletons) == [(AppModule, Tokens.DB), (AppModule, "db")]
    assert dict(manager.singletons) == {
        (AppModule, Tokens.DB): "from enum",
        (AppModule, "db"): "from str",
    }
    # A diagnostic reading the table has to show which of the two equal tokens each
    # slot belongs to, which the default object repr cannot.
    assert repr(manager.singletons).startswith("InstanceTable({")
    assert "<Tokens.DB: 'db'>" in repr(manager.singletons)

    del manager.singletons[(AppModule, Tokens.DB)]

    assert manager.get_singleton((AppModule, Tokens.DB)) is CACHE_MISS
    assert manager.get_singleton((AppModule, "db")) == "from str"

    manager.singletons.clear()

    assert len(manager.singletons) == 0


def test_a_consumer_seeing_two_modules_gets_each_one_s_own_instance() -> None:
    # Two equal tokens cannot be declared by one module, so the shape that reaches a
    # consumer is two modules exporting one each. Both instances are cached, and the
    # consumer holds one of each rather than whichever was built first twice.
    @Module(providers=[{"provide": Tokens.DB, "use_class": FromEnumToken}], exports=[Tokens.DB])
    class EnumModule:
        pass

    @Module(providers=[{"provide": "db", "use_class": FromStrToken}], exports=["db"])
    class StrModule:
        pass

    class Consumer:
        def __init__(self, from_enum: object, from_str: object) -> None:
            self.from_enum = from_enum
            self.from_str = from_str

    @Module(
        imports=[EnumModule, StrModule],
        providers=[{"provide": Consumer, "use_factory": Consumer, "inject": [Tokens.DB, "db"]}],
        exports=[Consumer],
    )
    class ConsumingModule:
        pass

    container = build_container(build_module_graph(ConsumingModule))
    consumer = cast(Any, container.resolve(Consumer, module=ConsumingModule))

    assert isinstance(consumer.from_enum, FromEnumToken)
    assert isinstance(consumer.from_str, FromStrToken)
    assert consumer.from_enum is not consumer.from_str
    assert (EnumModule, Tokens.DB) in container.scope_manager.singletons
    assert (StrModule, "db") in container.scope_manager.singletons


def test_a_consumer_seeing_a_true_token_and_a_one_token_gets_each_one_s_own_instance() -> None:
    @Module(providers=[{"provide": True, "use_class": FromEnumToken}], exports=[True])
    class TrueModule:
        pass

    @Module(providers=[{"provide": 1, "use_class": FromStrToken}], exports=[1])
    class OneModule:
        pass

    class Consumer:
        def __init__(self, from_true: object, from_one: object) -> None:
            self.from_true = from_true
            self.from_one = from_one

    @Module(
        imports=[TrueModule, OneModule],
        providers=[{"provide": Consumer, "use_factory": Consumer, "inject": [True, 1]}],
        exports=[Consumer],
    )
    class ConsumingModule:
        pass

    container = build_container(build_module_graph(ConsumingModule))
    consumer = cast(Any, container.resolve(Consumer, module=ConsumingModule))

    assert isinstance(consumer.from_true, FromEnumToken)
    assert isinstance(consumer.from_one, FromStrToken)
    assert consumer.from_true is not consumer.from_one
