"""The HTTP surface for creating and reading links."""

from __future__ import annotations

from dataclasses import asdict

from bustan import Auth, Controller, Get, HttpResponse, Post
from bustan.errors import ConflictException, NotFoundException

from .links_service import LinksService
from .models import CreateLinkPayload


@Controller("/links")
@Auth("bearer")
class LinksController:
    """Creating and inspecting links needs a token; following one does not."""

    def __init__(self, links: LinksService) -> None:
        self._links = links

    @Get("/")
    def list_links(self) -> list[dict[str, object]]:
        return [asdict(link) for link in self._links.list_links()]

    @Get("/{code}")
    def read_link(self, code: str) -> dict[str, object]:
        link = self._links.read_link(code)
        if link is None:
            raise NotFoundException(f"no link with code {code}")
        return asdict(link)

    @Post("/")
    def create_link(self, payload: CreateLinkPayload) -> HttpResponse:
        link = self._links.create_link(payload)
        if link is None:
            raise ConflictException("that code is already taken")
        return HttpResponse.json(
            asdict(link), status_code=201, headers={"location": f"/links/{link.code}"}
        )
