"""The short link itself: the thing a person actually clicks."""

from __future__ import annotations

from bustan import Controller, Get, HttpResponse, Public
from bustan.errors import NotFoundException

from .links_service import LinksService


@Controller("/")
@Public()
class RedirectController:
    """Follows a code to wherever it points.

    Public on purpose: a short link is useless if the person clicking it needs a token.
    """

    def __init__(self, links: LinksService) -> None:
        self._links = links

    @Get("/{code}")
    def follow(self, code: str) -> HttpResponse:
        link = self._links.follow_link(code)
        if link is None:
            raise NotFoundException(f"no link with code {code}")
        return HttpResponse(status_code=302, headers={"location": link.url})
