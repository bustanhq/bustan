"""The application object a request is served under, described rather than named.

``HttpRequest.app`` carries whatever the transport calls its application, which is not
always the one the framework assembled: an adapter may hand over its own server object
with the framework's application attached to it. The request path has to tell the two
apart to answer with the same application whichever way a request arrived, and it does
that here, by the shape assembly leaves behind rather than by a class it would have to
import from a layer above itself.

The container and the module graph are declared as plain objects because their types
belong to layers this package sits underneath. Nothing is lost: the framework names the
real types where it uses them, and what this declaration is for is recognition.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ApplicationRuntime(Protocol):
    """An assembled Bustan application, as the request path recognises one.

    Both members are artifacts of assembly, and an object carrying both was assembled
    by this framework. A transport's own application object carries neither, so a
    server handed to the framework in place of the application it serves is recognised
    as the server it is and unwrapped rather than mistaken for the application.
    """

    @property
    def container(self) -> object:
        """The container the application resolves its providers from."""

        raise NotImplementedError

    @property
    def module_graph(self) -> object:
        """The graph of modules the application was assembled from."""

        raise NotImplementedError
