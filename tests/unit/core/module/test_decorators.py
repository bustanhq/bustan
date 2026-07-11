"""Unit tests for module decorators and metadata coercion."""

from __future__ import annotations

from typing import Any, cast

import pytest

from bustan.core.errors import InvalidModuleError
from bustan.core.module.decorators import Global, Module
from bustan.core.module.metadata import get_module_metadata


def test_module_and_global_decorators_validate_targets_and_metadata() -> None:
    class ImportedModule:
        pass

    class Controller:
        pass

    class Provider:
        pass

    @Global()
    @Module(
        imports=[ImportedModule],
        controllers=[Controller],
        providers=[Provider],
        exports=[Provider],
    )
    class AppModule:
        pass

    metadata = get_module_metadata(AppModule)
    assert metadata is not None
    assert metadata.imports == (ImportedModule,)
    assert metadata.controllers == (Controller,)
    assert metadata.providers == (Provider,)
    assert metadata.exports == (Provider,)
    assert metadata.is_global is True

    with pytest.raises(InvalidModuleError, match="decorate classes"):
        Module()(cast(Any, object()))

    with pytest.raises(InvalidModuleError, match="decorate classes"):
        Global()(cast(Any, object()))

    with pytest.raises(InvalidModuleError, match="already decorated with @Module"):
        Global()(type("UndecoratedModule", (), {}))

    with pytest.raises(InvalidModuleError, match="iterable of objects"):
        Module(imports=cast(Any, "broken"))

    with pytest.raises(InvalidModuleError, match="iterable of objects"):
        Module(providers=cast(Any, object()))
