from bustan.core.module.metadata import get_module_metadata

from $package_name.app_module import AppModule
from $package_name.app_controller import AppController
from $package_name.app_service import AppService


def test_app_module_registers_controller_and_provider() -> None:
    meta = get_module_metadata(AppModule)
    assert AppController in meta.controllers
    assert AppService in meta.providers
