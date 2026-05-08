"""Unit tests for adapter conformance helpers."""

from __future__ import annotations

import builtins

import pytest

from bustan.platform.http import conformance as conformance_module


def test_load_adapter_rejects_unsupported_names() -> None:
    with pytest.raises(ValueError, match="Unsupported adapter 'unknown'"):
        conformance_module.load_adapter("unknown")


def test_load_test_client_wraps_missing_httpx_import(monkeypatch) -> None:
    real_import = builtins.__import__

    def fail_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "starlette.testclient":
            raise ModuleNotFoundError("No module named 'httpx'", name="httpx")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fail_import)

    with pytest.raises(ImportError, match="optional 'httpx' dependency"):
        conformance_module._load_test_client()


def test_load_test_client_re_raises_unrelated_missing_modules(monkeypatch) -> None:
    real_import = builtins.__import__

    def fail_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "starlette.testclient":
            raise ModuleNotFoundError("No module named 'other'", name="other")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fail_import)

    with pytest.raises(ModuleNotFoundError, match="other"):
        conformance_module._load_test_client()


def test_load_test_client_wraps_runtime_httpx_errors(monkeypatch) -> None:
    real_import = builtins.__import__

    def fail_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "starlette.testclient":
            raise RuntimeError(
                "The starlette.testclient module requires the httpx package to be installed."
            )
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fail_import)

    with pytest.raises(ImportError, match="optional 'httpx' dependency"):
        conformance_module._load_test_client()


def test_load_test_client_re_raises_unrelated_runtime_errors(monkeypatch) -> None:
    real_import = builtins.__import__

    def fail_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "starlette.testclient":
            raise RuntimeError("boom")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fail_import)

    with pytest.raises(RuntimeError, match="boom"):
        conformance_module._load_test_client()