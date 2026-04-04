"""Supported public API for the star package."""

from ._version import __version__
from .application import bootstrap, create_app
from .decorators import (
    controller,
    delete,
    get,
    injectable,
    module,
    patch,
    post,
    put,
    use_filters,
    use_guards,
    use_interceptors,
    use_pipes,
)
from .pipeline import ExceptionFilter, Guard, Interceptor, Pipe

__all__ = (
    "__version__",
    "ExceptionFilter",
    "Guard",
    "Interceptor",
    "Pipe",
    "bootstrap",
    "controller",
    "create_app",
    "delete",
    "get",
    "injectable",
    "module",
    "patch",
    "post",
    "put",
    "use_filters",
    "use_guards",
    "use_interceptors",
    "use_pipes",
)
