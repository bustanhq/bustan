"""Profile service for the pipeline example."""

from bustan import Injectable


@Injectable()
class ProfileService:
    def read_profile(self, user_id: str) -> dict[str, str]:
        return {
            "user_id": user_id,
            "plan": "pro",
        }