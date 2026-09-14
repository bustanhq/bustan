"""Litestar twins of the simple, synchronous and hundred-items routes.

Each twin answers the request its Bustan counterpart answers, with the same payload, through
the same stages: routing, a path parameter bound as an integer where the route has one, a
default-scoped service injected, the handler itself and JSON serialization. Each is written
the way Litestar writes it - a controller, a dependency provided once and cached, and for the
synchronous twin a handler Litestar runs on a worker thread - so what is compared is the two
frameworks used as each intends, not one imitating the other.

Two defaults are switched off. The OpenAPI schema, because no request reads it; and logging
configuration, because building an application with it configures the root logger for the
whole process, and every benchmark after this one would pay for a handler it never asked for.

Litestar's lifespan starts nothing these applications use - an event emitter no route emits
to - so the driver serves them as built.
"""

from __future__ import annotations

from applications import CatalogService
from litestar import Controller, Litestar, get
from litestar.di import NamedDependency, Provide
from litestar.params import FromPath


def _catalog() -> dict[str, Provide]:
    # Constructed on first use and cached from then on, which is how Bustan holds a
    # default-scoped provider, and resolved on the loop, which is where Bustan resolves one.
    return {"catalog": Provide(CatalogService, use_cache=True, sync_to_thread=False)}


class SimpleTwin(Controller):
    path = "/items"
    dependencies = _catalog()

    @get("/{item_id:int}")
    async def read_item(
        self, item_id: FromPath[int], catalog: NamedDependency[CatalogService]
    ) -> dict[str, object]:
        return catalog.read(item_id)


class SyncTwin(Controller):
    path = "/items"
    dependencies = _catalog()

    @get("/{item_id:int}", sync_to_thread=True)
    def read_item(
        self, item_id: FromPath[int], catalog: NamedDependency[CatalogService]
    ) -> dict[str, object]:
        return catalog.read(item_id)


class HundredItemsTwin(Controller):
    path = "/items"
    dependencies = _catalog()

    @get("/")
    async def list_items(self, catalog: NamedDependency[CatalogService]) -> list[dict[str, object]]:
        return catalog.list_items()


def build_twin(controller: type[Controller]) -> Litestar:
    """Return a Litestar application serving one twin and nothing else."""

    return Litestar(route_handlers=[controller], openapi_config=None, logging_config=None)
