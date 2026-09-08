"""The container's tables and instance caches are readable without being writable.

``app.container`` is documented, and the tables behind it were public mutable
attributes: a caller could assign into the binding table or a module's visibility map
and the framework would carry on as though the graph it validated still described the
application. The views are the supported way to read them, and every one refuses a
write rather than accepting it into a copy nobody reads - a copy is worse than a
refusal, because the write appears to succeed.

The suppression comments below are half the evidence. A view is typed as a ``Mapping``
rather than a ``MutableMapping``, so the type checker refuses the assignment before the
suite runs; each one has to be silenced here to reach the refusal the interpreter makes
at runtime, which is the other half.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from bustan import Controller, Get, Injectable, Module, create_app
from bustan.kernel.ioc.container import Container


@Injectable
class Clock:
    """A provider with nothing to do, so that the graph has something to bind."""

    def now(self) -> int:
        return 0


@Controller("/clock")
class ClockController:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock

    @Get("/")
    def read(self) -> dict[str, int]:
        return {"now": self.clock.now()}


@Module(providers=[Clock], controllers=[ClockController])
class AppModule:
    pass


def _container() -> Container:
    return create_app(AppModule).container


def _views(container: Container) -> dict[str, Mapping[Any, Any]]:
    return {
        "binding_view": container.binding_view,
        "visibility_view": container.visibility_view,
        "controller_module_view": container.controller_module_view,
        "singleton_instance_view": container.singleton_instance_view,
        "controller_instance_view": container.controller_instance_view,
        "durable_instance_view": container.durable_instance_view,
    }


def test_every_container_view_refuses_a_write() -> None:
    container = _container()

    for name, view in _views(container).items():
        held_before = len(view)

        with pytest.raises(TypeError, match="does not support item assignment"):
            view["a token nothing declares"] = object()  # ty: ignore[invalid-assignment]

        # The refusal is the point, and so is what follows from it: nothing was written
        # anywhere, so the container holds exactly what it held before the attempt.
        assert len(view) == held_before, name


def test_the_visibility_view_refuses_a_write_at_both_levels() -> None:
    container = _container()
    visible_to_the_root = container.visibility_view[AppModule]

    with pytest.raises(TypeError, match="does not support item assignment"):
        visible_to_the_root["a token nothing declares"] = AppModule  # ty: ignore[invalid-assignment]

    assert "a token nothing declares" not in container.visibility_view[AppModule]


def test_the_views_read_the_container_rather_than_a_copy_of_it() -> None:
    container = _container()
    singletons = container.singleton_instance_view

    assert (container.module_graph.root_key, Clock) not in singletons

    resolved = container.resolve(Clock, module=container.module_graph.root_key)

    # The same view object, read again: a copy taken before the resolution would still
    # be empty, and a caller holding one would be reading a container that no longer
    # exists.
    assert singletons[(container.module_graph.root_key, Clock)] is resolved


def test_the_views_show_what_the_module_graph_declared() -> None:
    container = _container()
    root = container.module_graph.root_key

    assert (root, Clock) in container.binding_view
    assert container.binding_view[(root, Clock)].token is Clock
    assert container.controller_module_view[ClockController] is root
    assert Clock in container.visibility_view[root]
    assert list(container.visibility_view) == [root]
    assert repr(container.visibility_view).startswith("VisibilityView({")
    assert "Clock" in repr(container.visibility_view)
