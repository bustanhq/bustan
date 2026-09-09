"""The root module: what this application is made of."""

from __future__ import annotations

from bustan import ConfigModule, HealthModule, MiddlewareConsumer, Module

from .identity_module import IdentityModule
from .request_id_middleware import RequestIdMiddleware
from .settings import Settings
from .store_indicator import HealthWiring, TaskStoreIndicator
from .store_module import StoreModule
from .tasks.tasks_module import TasksModule


@Module(
    imports=[
        # Configuration is global on purpose, and it is the exception rather than the
        # pattern: every module reads settings, so importing it everywhere would be
        # noise. Reach for is_global only when that is genuinely true.
        ConfigModule.for_root(env_file=".env", validation_schema=Settings),
        HealthModule.for_root(),
        StoreModule,
        IdentityModule,
        TasksModule,
    ],
    providers=[
        TaskStoreIndicator,
        HealthWiring,
    ],
)
class AppModule:
    """Wires the features, the store and the pipeline together."""

    def configure(self, consumer: MiddlewareConsumer) -> None:
        # The probes answer whether the process is alive; stamping them is noise.
        consumer.apply(RequestIdMiddleware).exclude("/health/live", "/health/ready")
