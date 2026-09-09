"""Dynamic cache module for the example."""

from bustan import DynamicModule, FactoryProvider, InjectionToken, Module, ValueProvider

from .cache_service import CacheService

CACHE_PREFIX = InjectionToken[str]("CACHE_PREFIX")


@Module(exports=[CacheService])
class CacheModule:
    @classmethod
    def register(cls, prefix: str) -> DynamicModule:
        return DynamicModule(
            module=cls,
            providers=(
                ValueProvider(provide=CACHE_PREFIX, use_value=prefix),
                FactoryProvider(
                    provide=CacheService, use_factory=CacheService, inject=(CACHE_PREFIX,)
                ),
            ),
            exports=(CacheService,),
        )
