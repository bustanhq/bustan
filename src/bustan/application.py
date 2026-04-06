"""Application bootstrap helpers exposed by the public API."""

from __future__ import annotations

from typing import Any, TypeVar, overload

from starlette.applications import Starlette
from starlette.datastructures import State

from .container import Container, build_container
from .injection import InjectionToken
from .lifecycle import build_lifespan
from .metadata import DynamicModule, ModuleKey
from .module_graph import ModuleGraph, ModuleNode, build_module_graph
from .routing import compile_routes

T = TypeVar("T")


class Application:
    """Strongly typed wrapper around the Starlette ASGI app and DI container."""

    def __init__(
        self,
        starlette_app: Starlette,
        container: Container,
        module_graph: ModuleGraph,
        root_key: ModuleKey,
    ):
        self._starlette_app = starlette_app
        self._container = container
        self._module_graph = module_graph
        self._root_key = root_key

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        """Implement ASGI protocol by forwarding to Starlette."""
        await self._starlette_app(scope, receive, send)

    @overload
    def get(self, token: type[T]) -> T: ...

    @overload
    def get(self, token: InjectionToken[T]) -> T: ...

    def get(self, token: object) -> Any:
        return self._container.resolve(token, module=self._root_key)

    def override(self, token: object, value: object) -> None:
        self._container.override(token, value, module=self._root_key)

    @property
    def container(self) -> Container:
        """Return the underlying DI container."""
        return self._container

    @property
    def module_graph(self) -> ModuleNode | ModuleGraph:
        """Return the compiled module graph."""
        return self._module_graph

    @property
    def root_module(self) -> type[object]:
        """Return the root module class."""
        if isinstance(self._root_key, type):
            return self._root_key
        return self._root_key.module

    @property
    def state(self) -> State:
        """Return the Starlette application state."""
        return self._starlette_app.state


def create_app(root_module: type[object] | DynamicModule) -> Application:
    """Build an Application from a decorated root module."""

    module_graph = build_module_graph(root_module)
    container = build_container(module_graph)
    routes = compile_routes(module_graph, container)

    starlette_app = Starlette(routes=list(routes), lifespan=build_lifespan(module_graph))

    return Application(
        starlette_app=starlette_app,
        container=container,
        module_graph=module_graph,
        root_key=module_graph.root_key,
    )


def bootstrap(root_module: type[object] | DynamicModule) -> Application:
    """Compatibility alias for create_app()."""
    return create_app(root_module)
