"""User directory service for the multi-module example."""

from bustan import Injectable


@Injectable()
class UserService:
    def list_users(self) -> list[dict[str, str]]:
        return [{"name": "Moses"}, {"name": "Ada"}]