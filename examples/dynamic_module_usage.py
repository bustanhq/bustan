import anyio
from bustan import (
    Module,
    DynamicModule,
    Injectable,
    InjectionToken,
    Controller,
    Get,
    create_app,
)

# 1. Define a typed injection token for configuration
CACHE_PREFIX = InjectionToken[str]("CACHE_PREFIX")


# 2. Define an Injectable service that depends on the token
@Injectable
class CacheService:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def get(self, key: str) -> str:
        return f"{self.prefix}{key}"


# 3. Define the Module with a dynamic 'register' method
@Module(
    exports=[CacheService],
)
class CacheModule:
    @classmethod
    def register(cls, prefix: str) -> DynamicModule:
        return DynamicModule(
            module=cls,
            providers=(
                # Inject the value for the CACHE_PREFIX token
                {"provide": CACHE_PREFIX, "use_value": prefix},
                # Use a factory to instantiate the service with the injected prefix
                {
                    "provide": CacheService,
                    "use_factory": lambda p: CacheService(p),
                    "inject": [CACHE_PREFIX],
                },
            ),
            exports=(CacheService,),
        )


# 4. Create a Controller to demonstrate usage
@Controller("/")
class AppController:
    def __init__(self, cache: CacheService) -> None:
        self.cache = cache

    @Get("/")
    def index(self):
        return {"cached_value": self.cache.get("example-key")}


# 5. Bootstrap the App importing the dynamic module
@Module(
    imports=[CacheModule.register("prod:")],
    controllers=[AppController],
)
class RootModule:
    pass


app = create_app(RootModule)


async def main():
    print("Starting example app on http://127.0.0.1:8000")
    # Use the new async listen() API
    await app.listen(8000)


if __name__ == "__main__":
    anyio.run(main)
