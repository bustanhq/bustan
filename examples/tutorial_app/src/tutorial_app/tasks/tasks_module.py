"""The tasks feature, as one importable unit."""

from __future__ import annotations

from bustan import Module

from ..identity_module import IdentityModule
from ..store_module import StoreModule
from .tasks_controller import TasksController
from .tasks_repository import TasksRepository
from .tasks_service import TasksService


@Module(
    imports=[StoreModule, IdentityModule],
    controllers=[TasksController],
    providers=[TasksService, TasksRepository],
    exports=[TasksService],
)
class TasksModule:
    """Exports the service only: the repository is this module's business."""
