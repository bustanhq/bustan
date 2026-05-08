"""Authentication metadata service for the multi-module example."""

from bustan import Injectable


@Injectable()
class AuthService:
    def issuer(self) -> str:
        return "bustan-auth"