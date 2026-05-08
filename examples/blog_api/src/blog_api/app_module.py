"""Root module for the blog API example."""

from bustan import Module

from .blog_controller import BlogController
from .blog_module import BlogModule
from .identity_module import IdentityModule


@Module(imports=[BlogModule, IdentityModule], controllers=[BlogController])
class AppModule:
    pass