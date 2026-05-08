"""Service layer for the blog API example."""

from bustan import Injectable

from .models import BlogPost, CreatePostPayload
from .post_repository import PostRepository


@Injectable()
class BlogService:
    def __init__(self, post_repository: PostRepository) -> None:
        self.post_repository = post_repository

    def list_posts(self, *, published: bool | None = None) -> list[BlogPost]:
        return self.post_repository.list_posts(published=published)

    def read_post(self, post_id: int) -> BlogPost | None:
        return self.post_repository.read_post(post_id)

    def create_post(self, payload: CreatePostPayload, *, created_by: str) -> BlogPost:
        return self.post_repository.create_post(payload, created_by=created_by)