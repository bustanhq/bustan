from bustan import Controller, create_app, Get, Injectable, Module


@Injectable
class AppService:
    def get_message(self) -> dict[str, str]:
        return {"message": "Hello from $project_name"}


@Controller("/")
class AppController:
    def __init__(self, app_service: AppService) -> None:
        self.app_service = app_service

    @Get("/")
    def read_root(self) -> dict[str, str]:
        return self.app_service.get_message()


@Module(controllers=[AppController], providers=[AppService], exports=[AppService])
class AppModule:
    pass


app = create_app(AppModule)


def main() -> None:
    import uvicorn

    uvicorn.run("$package_name.app:app", reload=True)


if __name__ == "__main__":
    main()
