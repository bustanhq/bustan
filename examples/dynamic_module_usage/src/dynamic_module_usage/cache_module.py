"""Dynamic cache module for the example."""

from bustan import DynamicModule, InjectionToken, Module

from .cache_service import CacheService

CACHE_PREFIX = InjectionToken[str]("CACHE_PREFIX")


@Module(exports=[CacheService])
class CacheModule:
    @classmethod
    def register(cls, prefix: str) -> DynamicModule:
        return DynamicModule(
            module=cls,
            providers=(
                {"provide": CACHE_PREFIX, "use_value": prefix},
                {
                    "provide": CacheService,
                    "use_factory": lambda resolved_prefix: CacheService(resolved_prefix),
                    "inject": [CACHE_PREFIX],
                },
            ),
            exports=(CacheService,),
        )