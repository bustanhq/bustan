"""Cache service for the dynamic module example."""

from bustan import Injectable


@Injectable()
class CacheService:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def get(self, key: str) -> str:
        return f"{self.prefix}{key}"