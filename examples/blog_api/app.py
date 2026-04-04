"""Reference-style example showing a small blog API built with star."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from star import controller, create_app, get, injectable, module, post
from starlette.requests import Request
from starlette.testclient import TestClient


@dataclass(frozen=True, slots=True)
class CreatePostPayload:
    title: str
    body: str
    published: bool = True


@dataclass(frozen=True, slots=True)
class BlogPost:
    id: int
    title: str
    body: str
    published: bool
    created_by: str


@injectable
class PostRepository:
    def __init__(self) -> None:
        self._posts = [
            BlogPost(
                id=1,
                title="Shipping an alpha",
                body="Tighten the release pipeline first.",
                published=True,
                created_by="system",
            )
        ]

    def list_posts(self, *, published: bool | None = None) -> list[BlogPost]:
        if published is None:
            return list(self._posts)
        return [post for post in self._posts if post.published is published]

    def read_post(self, post_id: int) -> BlogPost | None:
        for blog_post in self._posts:
            if blog_post.id == post_id:
                return blog_post
        return None

    def create_post(self, payload: CreatePostPayload, *, created_by: str) -> BlogPost:
        next_post = BlogPost(
            id=len(self._posts) + 1,
            title=payload.title,
            body=payload.body,
            published=payload.published,
            created_by=created_by,
        )
        self._posts.append(next_post)
        return next_post


@injectable
class BlogService:
    def __init__(self, post_repository: PostRepository) -> None:
        self.post_repository = post_repository

    def list_posts(self, *, published: bool | None = None) -> list[BlogPost]:
        return self.post_repository.list_posts(published=published)

    def read_post(self, post_id: int) -> BlogPost | None:
        return self.post_repository.read_post(post_id)

    def create_post(self, payload: CreatePostPayload, *, created_by: str) -> BlogPost:
        return self.post_repository.create_post(payload, created_by=created_by)


@injectable(scope="request")
class RequestActor:
    def __init__(self, request: Request) -> None:
        self.user_id = request.headers.get("x-user-id", "anonymous")


@module(providers=[PostRepository, BlogService], exports=[BlogService])
class BlogModule:
    pass


@module(providers=[RequestActor], exports=[RequestActor])
class IdentityModule:
    pass


@controller("/posts")
class BlogController:
    def __init__(self, blog_service: BlogService, request_actor: RequestActor) -> None:
        self.blog_service = blog_service
        self.request_actor = request_actor

    @get("/")
    def list_posts(self, published: bool | None = None) -> list[dict[str, object]]:
        return [asdict(post) for post in self.blog_service.list_posts(published=published)]

    @get("/{post_id}")
    def read_post(self, post_id: int) -> dict[str, object] | None:
        post = self.blog_service.read_post(post_id)
        return None if post is None else asdict(post)

    @post("/")
    def create_post(self, payload: CreatePostPayload) -> dict[str, object]:
        post = self.blog_service.create_post(payload, created_by=self.request_actor.user_id)
        return asdict(post)


@module(imports=[BlogModule, IdentityModule], controllers=[BlogController])
class AppModule:
    pass


app = create_app(AppModule)


def demo() -> None:
    """Show the seeded list endpoint and a write that carries request-local context."""

    with TestClient(app) as client:
        print(client.get("/posts").json())
        print(
            client.post(
                "/posts",
                headers={"x-user-id": "ada"},
                json={
                    "title": "Request-scoped context",
                    "body": "Controllers can mix singleton services with request-local state.",
                    "published": True,
                },
            ).json()
        )


if __name__ == "__main__":
    demo()