"""Feature module for post storage and business logic."""

from bustan import Module

from .blog_service import BlogService
from .post_repository import PostRepository


@Module(providers=[PostRepository, BlogService], exports=[BlogService])
class BlogModule:
    pass