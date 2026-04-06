"""Provider override management for testing and runtime composition."""

from __future__ import annotations

from ..errors import ProviderResolutionError
from ..module.dynamic import ModuleKey
from ..utils import _display_name, _qualname
from .registry import Registry


class OverrideManager:
    """Manages replacement objects for registered providers."""

    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self._overrides: dict[tuple[ModuleKey, object], object] = {}

    def override(self, token: object, value: object, *, module: ModuleKey | None = None) -> None:
        """Register a replacement object for a provider."""
        override_key = self._resolve_override_key(token, module)
        self._overrides[override_key] = value

    def clear_override(self, token: object, *, module: ModuleKey | None = None) -> None:
        """Remove any override registered for a provider."""
        override_key = self._resolve_override_key(token, module)
        self._overrides.pop(override_key, None)

    def has_override(self, token: object, *, module: ModuleKey | None = None) -> bool:
        try:
            override_key = self._resolve_override_key(token, module)
            return override_key in self._overrides
        except ProviderResolutionError:
            return False

    def get_override(self, token: object, *, module: ModuleKey | None = None) -> object | None:
        try:
            override_key = self._resolve_override_key(token, module)
            return self._overrides.get(override_key)
        except ProviderResolutionError:
            return None

    def _resolve_override_key(
        self,
        token: object,
        module_key: ModuleKey | None,
    ) -> tuple[ModuleKey, object]:
        if module_key is not None:
            override_key = (module_key, token)
            if override_key not in self.registry.bindings:
                raise ProviderResolutionError(
                    f"{_display_name(token)} is not registered in {_display_name(module_key)}"
                )
            return override_key

        declaring_modules = [
            registered_module
            for registered_module, registered_token in self.registry.bindings
            if registered_token is token
        ]

        if not declaring_modules:
            raise ProviderResolutionError(f"{_qualname(token)} is not registered in the container")

        if len(declaring_modules) > 1:
            module_names = ", ".join(
                _display_name(registered_module) for registered_module in declaring_modules
            )
            raise ProviderResolutionError(
                f"{_display_name(token)} is registered in multiple modules ({module_names}); "
                "specify module_key when overriding it"
            )

        return declaring_modules[0], token
