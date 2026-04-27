from bustan import Injectable


@Injectable
class AppService:
    def get_message(self) -> dict[str, str]:
        return {"message": "Hello from $project_name"}
