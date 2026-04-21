"""Metadata and hook definitions for the module lifecycle."""

from __future__ import annotations

LifecycleHookName: tuple[str, ...] = (
    "on_module_init",
    "on_app_startup",
    "on_app_shutdown",
    "on_module_destroy",
)
