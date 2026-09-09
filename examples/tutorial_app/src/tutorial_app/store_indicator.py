"""What readiness asks before the application is sent traffic."""

from __future__ import annotations

from bustan import HealthIndicatorResult, HealthService, Injectable

from .task_store import TaskStore


@Injectable()
class TaskStoreIndicator:
    """Reports whether the store can still answer a query."""

    name = "task-store"

    def __init__(self, store: TaskStore) -> None:
        self._store = store

    async def check(self) -> HealthIndicatorResult:
        if self._store.is_answering():
            return HealthIndicatorResult.up()
        # A detail crosses a trust boundary: no path, no driver message, no credential.
        return HealthIndicatorResult.down("the task store is not answering")


@Injectable()
class HealthWiring:
    """Registers the indicator early enough that readiness is never wrong."""

    def __init__(self, health: HealthService, indicator: TaskStoreIndicator) -> None:
        self._health = health
        self._indicator = indicator

    def on_module_init(self) -> None:
        self._health.register_readiness(self._indicator)
