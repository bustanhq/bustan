"""The links feature, as one importable unit."""

from __future__ import annotations

from bustan import Module

from ..identity_module import IdentityModule
from ..store_module import StoreModule
from .links_controller import LinksController
from .links_repository import LinksRepository
from .links_service import LinksService
from .redirect_controller import RedirectController


@Module(
    imports=[StoreModule, IdentityModule],
    controllers=[LinksController, RedirectController],
    providers=[LinksService, LinksRepository],
    exports=[LinksService],
)
class LinksModule:
    """Exports the service only: the repository is this module's business."""
