"""Who the caller is, decided once per request."""

from __future__ import annotations

from dataclasses import dataclass

from bustan import ConfigService, ExecutionContext, Injectable


@dataclass(frozen=True, slots=True)
class TokenPrincipal:
    """The caller a request is served for.

    Satisfies the framework's ``Principal`` protocol: an id, the roles it holds and the
    permissions it carries.
    """

    id: str
    roles: tuple[str, ...]
    permissions: tuple[str, ...]


@Injectable()
class BearerAuthenticator:
    """Reads a bearer token and says who is calling, or that nobody is.

    Returning None is a refusal: the policy guard answers 401. This compares against one
    configured token because the tutorial is about the wiring; a real one verifies a
    signature or asks an identity provider, and nothing around it changes.
    """

    def __init__(self, config: ConfigService) -> None:
        self._token = str(config.get_or_throw("API_TOKEN"))

    def authenticate(self, context: ExecutionContext) -> TokenPrincipal | None:
        request = context.request
        header = "" if request is None else request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or token != self._token:
            return None
        return TokenPrincipal(id="tutorial-user", roles=("author",), permissions=())
