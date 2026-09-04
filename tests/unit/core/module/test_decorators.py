"""Unit tests for module decorators and metadata coercion."""

from __future__ import annotations

from typing import Any, cast

import pytest

from bustan.core.errors import InvalidModuleError
from bustan.core.module.decorators import Global, Module
from bustan.core.module.metadata import ModuleMetadata, get_module_metadata


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


def test_module_refuses_unordered_collections_and_bare_mappings() -> None:
    # Declaration order decides construction order and lifecycle hook order, so a set
    # hands the application an order that can differ between interpreter runs. A bare
    # mapping is worse: it iterates as its keys, so a lone provider definition was read
    # as the strings 'provide' and 'use_value'.
    class Alpha:
        pass

    class Beta:
        pass

    with pytest.raises(InvalidModuleError, match="does not preserve declaration order"):
        Module(providers=cast(Any, {Alpha, Beta}))

    with pytest.raises(InvalidModuleError, match="does not preserve declaration order"):
        Module(controllers=cast(Any, frozenset({Alpha})))

    with pytest.raises(InvalidModuleError, match="does not preserve declaration order"):
        Module(exports=cast(Any, {Alpha, Beta}))

    with pytest.raises(InvalidModuleError, match="inside a sequence"):
        Module(providers=cast(Any, {"provide": "token", "use_value": 1}))

    # A view over a mapping keeps the mapping's insertion order, so it stays usable.
    ordered = Module(providers=cast(Any, {Alpha: 1, Beta: 2}.keys()))(type("Ordered", (), {}))
    assert get_module_metadata(ordered) == ModuleMetadata(providers=(Alpha, Beta))


def test_module_refuses_a_second_declaration_on_one_class() -> None:
    class Alpha:
        pass

    class Beta:
        pass

    with pytest.raises(InvalidModuleError, match="already decorated with @Module"):

        @Module(providers=[Alpha])
        @Module(providers=[Beta])
        class Doubled:
            pass


def test_module_metadata_belongs_to_the_class_it_was_written_on() -> None:
    class Alpha:
        pass

    @Module(providers=[Alpha])
    class BaseModule:
        pass

    # A subclass has no declaration of its own, so it may still be given one.
    @Module()
    class DerivedModule(BaseModule):
        pass

    assert get_module_metadata(BaseModule) == ModuleMetadata(providers=(Alpha,))
    assert get_module_metadata(DerivedModule) == ModuleMetadata()
