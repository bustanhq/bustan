"""Post repository for the blog API example."""

from bustan import Injectable

from .models import BlogPost, CreatePostPayload


@Injectable()
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