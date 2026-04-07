"""Abstract base class for HTTP framework adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable


class AbstractHttpAdapter(ABC):
    """Base class for decoupling Bustan from specific web frameworks.

    Adapters are responsible for wrapping the underlying framework instance
    (e.g., Starlette, FastAPI) and handling route registration and 
    server initialization.
    """

    @abstractmethod
    def get_instance(self) -> Any:
        """Return the underlying framework instance (e.g., Starlette App)."""
        pass

    @abstractmethod
    def register_routes(self, routes: list[Any]) -> None:
        """Register compiled routes into the underlying engine."""
        pass

    @abstractmethod
    async def listen(
        self, 
        port: int, 
        host: str = "127.0.0.1", 
        reload: bool = False, 
        **kwargs: Any
    ) -> None:
        """Start the ASGI server asynchronously."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Shutdown the underlying server/engine."""
        pass

    @abstractmethod
    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        """All Bustan HTTP adapters must be valid ASGI callables."""
        pass
