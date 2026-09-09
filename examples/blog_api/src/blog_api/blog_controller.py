"""Controller layer for the blog API example."""

from dataclasses import asdict

from bustan import Controller, Get, Post, Scope
from bustan.errors import NotFoundException

from .blog_service import BlogService
from .models import CreatePostPayload
from .request_actor import RequestActor


@Controller("/posts", scope=Scope.REQUEST)
class BlogController:
    def __init__(self, blog_service: BlogService, request_actor: RequestActor) -> None:
        self.blog_service = blog_service
        self.request_actor = request_actor

    @Get("/")
    def list_posts(self, published: bool | None = None) -> list[dict[str, object]]:
        return [asdict(post) for post in self.blog_service.list_posts(published=published)]

    @Get("/{post_id}")
    def read_post(self, post_id: int) -> dict[str, object]:
        post = self.blog_service.read_post(post_id)
        if post is None:
            # Returning None would answer 204, which tells a caller there is nothing to
            # send rather than that there is no such post. Raise, and the error contract
            # answers 404 as a problem document.
            raise NotFoundException(f"no post with id {post_id}")
        return asdict(post)

    @Post("/")
    def create_post(self, payload: CreatePostPayload) -> dict[str, object]:
        post = self.blog_service.create_post(payload, created_by=self.request_actor.user_id)
        return asdict(post)
