"""What the application does with links, apart from how they are stored or served."""

from __future__ import annotations

import secrets
import string

from bustan import ConfigService, Injectable

from .links_repository import LinksRepository
from .models import CreateLinkPayload, Link

ALPHABET = string.ascii_lowercase + string.digits


@Injectable()
class LinksService:
    """Holds the rules. The controller translates HTTP; this decides."""

    def __init__(self, repository: LinksRepository, config: ConfigService) -> None:
        self._repository = repository
        self._code_length = int(config.get("CODE_LENGTH", 6))
        self._page_size = int(config.get("PAGE_SIZE", 20))

    def list_links(self) -> list[Link]:
        return self._repository.list_links(self._page_size)

    def read_link(self, code: str) -> Link | None:
        return self._repository.read_link(code)

    def follow_link(self, code: str) -> Link | None:
        """Return the link a code points at, counting the visit."""
        link = self._repository.read_link(code)
        if link is not None:
            self._repository.count_visit(code)
        return link

    def create_link(self, payload: CreateLinkPayload) -> Link | None:
        """Shorten a URL, or answer None when the requested code is taken."""
        if payload.code is not None:
            return self._repository.create_link(payload.code, str(payload.url))
        for _ in range(5):
            code = "".join(secrets.choice(ALPHABET) for _ in range(self._code_length))
            link = self._repository.create_link(code, str(payload.url))
            if link is not None:
                return link
        return None
