"""Production greeting service for the testing example."""

from bustan import Injectable


@Injectable()
class GreetingService:
    def greet(self) -> str:
        return "production"