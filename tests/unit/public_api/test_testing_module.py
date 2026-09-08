"""Unit tests over the supported public surface of the testing helpers."""

from __future__ import annotations

import bustan.testing as bustan_testing
from bustan.testing import AsgiTestClient as InternalAsgiTestClient
from bustan.testing import AsgiTestResponse as InternalAsgiTestResponse
from bustan.testing import CompiledTestingModule as InternalCompiledTestingModule
from bustan.testing import PipelineOverrideRegistry as InternalPipelineOverrideRegistry
from bustan.testing import TestingModuleBuilder as InternalTestingModuleBuilder
from bustan.testing import (
    create_test_app,
    create_test_module,
    create_testing_module,
    override_provider,
)


def test_testing_module_exposes_the_supported_helpers() -> None:
    assert bustan_testing.__all__ == (
        "AsgiTestClient",
        "AsgiTestResponse",
        "CompiledTestingModule",
        "PipelineOverrideRegistry",
        "TestingModuleBuilder",
        "create_test_app",
        "create_test_module",
        "create_testing_module",
        "override_provider",
    )
    assert bustan_testing.AsgiTestClient is InternalAsgiTestClient
    assert bustan_testing.AsgiTestResponse is InternalAsgiTestResponse
    assert bustan_testing.CompiledTestingModule is InternalCompiledTestingModule
    assert bustan_testing.PipelineOverrideRegistry is InternalPipelineOverrideRegistry
    assert bustan_testing.TestingModuleBuilder is InternalTestingModuleBuilder
    assert bustan_testing.create_test_app is create_test_app
    assert bustan_testing.create_test_module is create_test_module
    assert bustan_testing.create_testing_module is create_testing_module
    assert bustan_testing.override_provider is override_provider
