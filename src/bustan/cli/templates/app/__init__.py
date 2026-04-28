from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

from bustan import create_app as _create_bustan_app

_PACKAGE_DIR = Path(__file__).resolve().parent


def _load_local_module(alias: str, filename: str):
    module_name = f"{__name__}.{alias}"
    if module_name in sys.modules:
        return sys.modules[module_name]

    module_spec = spec_from_file_location(module_name, _PACKAGE_DIR / filename)
    if module_spec is None or module_spec.loader is None:
        raise ImportError(f"Could not load {filename!r} in package {__name__!r}")

    module = module_from_spec(module_spec)
    sys.modules[module_name] = module
    module_spec.loader.exec_module(module)
    return module


_app_service_module = _load_local_module("_app_service", "app.service.py")
AppService = _app_service_module.AppService

_app_controller_module = _load_local_module("_app_controller", "app.controller.py")
AppController = _app_controller_module.AppController

_app_module_module = _load_local_module("_app_module", "app.module.py")
AppModule = _app_module_module.AppModule

app = _create_bustan_app(AppModule)

__all__ = ["AppController", "AppModule", "AppService", "app"]
