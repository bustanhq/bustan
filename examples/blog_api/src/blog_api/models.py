"""Models used by the blog API example."""

from dataclasses import dataclass


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