"""Recursive dependency resolution and constructor injection kernel."""

from __future__ import annotations

import inspect
import sys
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated, TypeVar, cast, get_args, get_origin, get_type_hints

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response

from ...common.decorators.injectable import InjectMarker, OptionalDependencyMarker
from ...common.types import ProviderScope
from ..errors import ProviderResolutionError
from ..module.dynamic import ModuleKey
from ..utils import _display_name, _qualname
from .overrides import OverrideManager
from .registry import Binding, Registry
from .scopes import ScopeManager
from .tokens import APPLICATION, INQUIRER, REQUEST, RESPONSE

ResolvedT = TypeVar("ResolvedT")
FRAMEWORK_OWNED_TYPES = frozenset({Request, Response, Starlette})


@dataclass(frozen=True, slots=True)
class ResolutionFrame:
	"""One active dependency resolution step."""

	token: object
	module: ModuleKey


@dataclass(frozen=True, slots=True)
class ParsedDependency:
	"""Parsed constructor dependency metadata."""

	annotation: object
	token: object
	optional: bool


class Resolver:
	"""Handles the recursive resolution of providers and classes."""

	def __init__(
		self,
		registry: Registry,
		scope_manager: ScopeManager,
		override_manager: OverrideManager,
	) -> None:
		self.registry = registry
		self.scope_manager = scope_manager
		self.override_manager = override_manager
		self.resolution_stack: ContextVar[tuple[ResolutionFrame, ...]] = ContextVar(
			"bustan_resolution_stack", default=()
		)

	def resolve(
		self,
		token: object,
		*,
		module: ModuleKey,
		request: Request | None = None,
	) -> object:
		"""Resolve a provider visible from the given module."""

		active_request_token = self.scope_manager.push_request(request)
		try:
			if self.override_manager.has_override(token, module=module):
				return self.override_manager.get_override(token, module=module)

			declaring_module = self._get_declaring_module(token, module)
			binding_key = (declaring_module, token)
			binding = self.registry.get_binding(binding_key)
			if binding is None:
				raise ProviderResolutionError(f"Binding not found for {token!r}")

			cached = self._get_cached_instance(binding, binding_key, declaring_module, token)
			if cached is not None:
				return cached

			if self._binding_requires_async(binding):
				raise ProviderResolutionError(
					f"{_qualname(token)} in {_display_name(declaring_module)} uses an async factory. "
					"Initialize the application before resolving it synchronously."
				)

			current_stack = self.resolution_stack.get()
			if any(frame.token == token for frame in current_stack):
				cycle_path = " -> ".join(
					_display_name(frame.token)
					for frame in (*current_stack, ResolutionFrame(token, declaring_module))
				)
				raise ProviderResolutionError(
					f"Circular provider dependencies detected: {cycle_path}"
				)

			stack_token = self.resolution_stack.set(
				(*current_stack, ResolutionFrame(token, declaring_module))
			)
			try:
				instance = self._resolve_binding(binding, module_key=declaring_module)
			finally:
				self.resolution_stack.reset(stack_token)

			return self._cache_instance(binding, binding_key, declaring_module, token, instance)
		finally:
			self.scope_manager.pop_request(active_request_token)

	async def resolve_async(
		self,
		token: object,
		*,
		module: ModuleKey,
		request: Request | None = None,
	) -> object:
		"""Resolve a provider and await async factories when required."""

		active_request_token = self.scope_manager.push_request(request)
		try:
			if self.override_manager.has_override(token, module=module):
				return self.override_manager.get_override(token, module=module)

			declaring_module = self._get_declaring_module(token, module)
			binding_key = (declaring_module, token)
			binding = self.registry.get_binding(binding_key)
			if binding is None:
				raise ProviderResolutionError(f"Binding not found for {token!r}")

			cached = self._get_cached_instance(binding, binding_key, declaring_module, token)
			if cached is not None:
				return cached

			current_stack = self.resolution_stack.get()
			if any(frame.token == token for frame in current_stack):
				cycle_path = " -> ".join(
					_display_name(frame.token)
					for frame in (*current_stack, ResolutionFrame(token, declaring_module))
				)
				raise ProviderResolutionError(
					f"Circular provider dependencies detected: {cycle_path}"
				)

			stack_token = self.resolution_stack.set(
				(*current_stack, ResolutionFrame(token, declaring_module))
			)
			try:
				instance = await self._resolve_binding_async(binding, module_key=declaring_module)
			finally:
				self.resolution_stack.reset(stack_token)

			return self._cache_instance(binding, binding_key, declaring_module, token, instance)
		finally:
			self.scope_manager.pop_request(active_request_token)

	def _resolve_binding(self, binding: Binding, module_key: ModuleKey) -> object:
		if binding.resolver_kind == "value":
			return binding.target
		if binding.resolver_kind == "existing":
			return self.resolve(
				binding.target,
				module=module_key,
				request=self.scope_manager.active_request.get(),
			)
		if binding.resolver_kind == "class":
			cls_target = cast(type[object], binding.target)
			return self.instantiate_class(
				cls_target,
				module=module_key,
				request=self.scope_manager.active_request.get(),
			)
		if binding.resolver_kind == "factory":
			factory, inject_tokens = cast(tuple[Callable[..., object], tuple[object, ...]], binding.target)
			return self.call_factory(
				factory,
				inject_tokens,
				module=module_key,
				request=self.scope_manager.active_request.get(),
			)
		raise ProviderResolutionError(f"Unknown resolver kind: {binding.resolver_kind}")

	async def _resolve_binding_async(self, binding: Binding, module_key: ModuleKey) -> object:
		if binding.resolver_kind == "value":
			return binding.target
		if binding.resolver_kind == "existing":
			return await self.resolve_async(
				binding.target,
				module=module_key,
				request=self.scope_manager.active_request.get(),
			)
		if binding.resolver_kind == "class":
			cls_target = cast(type[object], binding.target)
			return self.instantiate_class(
				cls_target,
				module=module_key,
				request=self.scope_manager.active_request.get(),
			)
		if binding.resolver_kind == "factory":
			factory, inject_tokens = cast(tuple[Callable[..., object], tuple[object, ...]], binding.target)
			return await self.call_factory_async(
				factory,
				inject_tokens,
				module=module_key,
				request=self.scope_manager.active_request.get(),
			)
		raise ProviderResolutionError(f"Unknown resolver kind: {binding.resolver_kind}")

	def instantiate_class(
		self,
		cls: type[object],
		*,
		module: ModuleKey,
		request: Request | None = None,
	) -> object:
		"""Resolve a fresh controller or class instance for request handling."""

		active_request_token = self.scope_manager.push_request(request)
		try:
			positional_arguments, keyword_arguments = self._resolve_constructor_dependencies(
				cls,
				module,
			)
			return cls(*positional_arguments, **keyword_arguments)
		finally:
			self.scope_manager.pop_request(active_request_token)

	def call_factory(
		self,
		factory: Callable[..., object],
		inject: tuple[object, ...],
		*,
		module: ModuleKey,
		request: Request | None = None,
	) -> object:
		"""Resolve parameters using inject mapping and call the factory."""

		active_request_token = self.scope_manager.push_request(request)
		try:
			args = [
				self.resolve(token, module=module, request=self.scope_manager.active_request.get())
				for token in inject
			]
			result = factory(*args)
			if inspect.isawaitable(result):
				raise ProviderResolutionError(
					f"Factory {_qualname(factory)} in {_display_name(module)} returned an awaitable "
					"during synchronous resolution"
				)
			return result
		finally:
			self.scope_manager.pop_request(active_request_token)

	async def call_factory_async(
		self,
		factory: Callable[..., object],
		inject: tuple[object, ...],
		*,
		module: ModuleKey,
		request: Request | None = None,
	) -> object:
		"""Resolve parameters and call a factory that may be asynchronous."""

		active_request_token = self.scope_manager.push_request(request)
		try:
			args = [
				await self.resolve_async(
					token,
					module=module,
					request=self.scope_manager.active_request.get(),
				)
				for token in inject
			]
			result = factory(*args)
			if inspect.isawaitable(result):
				return await result
			return result
		finally:
			self.scope_manager.pop_request(active_request_token)

	def _get_declaring_module(self, token: object, module_key: ModuleKey) -> ModuleKey:
		visibility = self.registry.module_visibility.get(module_key)
		if visibility is None:
			raise ProviderResolutionError(
				f"{_display_name(module_key)} is not part of the application container"
			)

		declaring_module = visibility.get(token)
		if declaring_module is None:
			raise ProviderResolutionError(
				f"{_qualname(token)} is not available to {_display_name(module_key)}. "
				"Dependencies must come from the same module or an imported module export"
			)
		return declaring_module

	def _resolve_constructor_dependencies(
		self,
		class_cls: type[object],
		module_key: ModuleKey,
	) -> tuple[tuple[object, ...], dict[str, object]]:
		owner_is_controller = class_cls in self.registry.controller_modules
		is_request_scoped = False
		is_durable_scoped = False

		for binding in self.registry.bindings.values():
			if binding.resolver_kind == "class" and binding.target is class_cls:
				if binding.scope is ProviderScope.REQUEST:
					is_request_scoped = True
				elif binding.scope is ProviderScope.DURABLE:
					is_durable_scoped = True
				break

		constructor = class_cls.__init__
		if constructor is object.__init__:
			return (), {}

		try:
			signature = inspect.signature(constructor)
		except (TypeError, ValueError) as exc:
			raise ProviderResolutionError(
				f"Could not inspect {_qualname(class_cls)}.__init__: {exc}"
			) from exc

		try:
			type_hints = get_type_hints(
				constructor,
				globalns=getattr(
					sys.modules.get(class_cls.__module__),
					"__dict__",
					constructor.__globals__,
				),
				localns=self._build_type_hint_namespace(class_cls, module_key),
				include_extras=True,
			)
		except (NameError, TypeError) as exc:
			raise ProviderResolutionError(
				f"Could not resolve type hints for {_qualname(class_cls)}.__init__: {exc}"
			) from exc

		positional_arguments: list[object] = []
		keyword_arguments: dict[str, object] = {}
		active_request = self.scope_manager.active_request.get()

		for parameter in signature.parameters.values():
			if parameter.name == "self":
				continue

			if parameter.kind in (
				inspect.Parameter.VAR_POSITIONAL,
				inspect.Parameter.VAR_KEYWORD,
			):
				raise ProviderResolutionError(
					f"{_qualname(class_cls)}.__init__ uses unsupported variadic parameter {parameter.name!r}"
				)

			annotation = type_hints.get(parameter.name)
			if annotation is None:
				raise ProviderResolutionError(
					f"{_qualname(class_cls)}.__init__ parameter {parameter.name!r} is missing a type annotation"
				)

			dependency = self._parse_dependency(annotation)
			resolved = self._resolve_special_token(
				dependency,
				class_cls=class_cls,
				parameter_name=parameter.name,
				active_request=active_request,
				owner_is_controller=owner_is_controller,
				is_request_scoped=is_request_scoped,
				is_durable_scoped=is_durable_scoped,
			)
			if resolved is _MISSING:
				if dependency.optional and not self._is_dependency_available(dependency.token, module_key):
					resolved = None
				else:
					resolved = self._resolve_declared_dependency(
						dependency,
						class_cls=class_cls,
						parameter_name=parameter.name,
						module_key=module_key,
						owner_is_controller=owner_is_controller,
						is_request_scoped=is_request_scoped,
						active_request=active_request,
					)

			if parameter.kind in (
				inspect.Parameter.POSITIONAL_ONLY,
				inspect.Parameter.POSITIONAL_OR_KEYWORD,
			):
				positional_arguments.append(resolved)
			else:
				keyword_arguments[parameter.name] = resolved

		return tuple(positional_arguments), keyword_arguments

	def _resolve_declared_dependency(
		self,
		dependency: ParsedDependency,
		*,
		class_cls: type[object],
		parameter_name: str,
		module_key: ModuleKey,
		owner_is_controller: bool,
		is_request_scoped: bool,
		active_request: Request | None,
	) -> object:
		if not isinstance(dependency.annotation, str):
			dependency_declaring_module = self.registry.module_visibility.get(module_key, {}).get(
				dependency.token
			)
			if dependency_declaring_module is not None:
				dependency_binding = self.registry.bindings.get(
					(dependency_declaring_module, dependency.token)
				)
				if (
					dependency_binding is not None
					and dependency_binding.scope is ProviderScope.REQUEST
					and not is_request_scoped
					and not owner_is_controller
				):
					raise ProviderResolutionError(
						f"{_qualname(class_cls)}.__init__ parameter {parameter_name!r} depends on "
						f"request-scoped provider {_qualname(dependency.token)}, which can only be injected "
						"into request-scoped providers or controllers"
					)

		try:
			return self.resolve(dependency.token, module=module_key, request=active_request)
		except ProviderResolutionError as exc:
			raise ProviderResolutionError(
				f"{_qualname(class_cls)}.__init__ parameter {parameter_name!r} in "
				f"{_display_name(module_key)} failed to resolve {_qualname(dependency.token)} "
				f"(dependency path: {self._format_dependency_path(dependency.token)}): {exc}"
			) from exc

	def _resolve_special_token(
		self,
		dependency: ParsedDependency,
		*,
		class_cls: type[object],
		parameter_name: str,
		active_request: Request | None,
		owner_is_controller: bool,
		is_request_scoped: bool,
		is_durable_scoped: bool,
	) -> object:
		allow_request_runtime = owner_is_controller or is_request_scoped or is_durable_scoped

		if dependency.annotation is Request or dependency.token is REQUEST:
			if allow_request_runtime and active_request is not None:
				return active_request
			if dependency.token is REQUEST:
				raise ProviderResolutionError(
					f"{_qualname(class_cls)}.__init__ parameter {parameter_name!r} requested REQUEST, "
					"which is only available during request-scoped resolution"
				)
			raise ProviderResolutionError(
				f"{_qualname(class_cls)}.__init__ parameter {parameter_name!r} requests "
				"framework-owned type Request, which is not available in provider DI"
			)

		if dependency.annotation is Response or dependency.token is RESPONSE:
			response = self.scope_manager.active_response.get()
			if response is not None:
				return response
			raise ProviderResolutionError(
				f"{_qualname(class_cls)}.__init__ parameter {parameter_name!r} requested RESPONSE, "
				"which is not available in the current runtime scope"
			)

		if dependency.annotation is Starlette or dependency.token is APPLICATION:
			application = self.scope_manager.active_application.get()
			if application is not None:
				return application
			if active_request is not None and hasattr(active_request, "app"):
				return active_request.app
			if dependency.annotation is Starlette:
				raise ProviderResolutionError(
					f"{_qualname(class_cls)}.__init__ parameter {parameter_name!r} requests "
					"framework-owned type Starlette, which is not available in provider DI"
				)
			raise ProviderResolutionError(
				f"{_qualname(class_cls)}.__init__ parameter {parameter_name!r} requested APPLICATION, "
				"which is not available in the current runtime scope"
			)

		if dependency.token is INQUIRER:
			current_stack = self.resolution_stack.get()
			if not current_stack:
				raise ProviderResolutionError(
					f"{_qualname(class_cls)}.__init__ parameter {parameter_name!r} requested INQUIRER, "
					"which is only available during nested provider resolution"
				)
			return current_stack[-1].token

		return _MISSING

	def _parse_dependency(self, annotation: object) -> ParsedDependency:
		explicit_token: object | None = None
		optional = False
		normalized_annotation = annotation

		if get_origin(annotation) is Annotated:
			annotation_args = get_args(annotation)
			normalized_annotation = annotation_args[0]
			for marker in annotation_args[1:]:
				if isinstance(marker, InjectMarker):
					explicit_token = marker.token
				elif isinstance(marker, OptionalDependencyMarker):
					optional = True

		return ParsedDependency(
			annotation=normalized_annotation,
			token=explicit_token if explicit_token is not None else normalized_annotation,
			optional=optional,
		)

	def _build_type_hint_namespace(
		self,
		class_cls: type[object],
		module_key: ModuleKey,
	) -> dict[str, object]:
		namespace: dict[str, object] = {
			class_cls.__name__: class_cls,
			Request.__name__: Request,
			Response.__name__: Response,
			Starlette.__name__: Starlette,
			"Annotated": Annotated,
		}

		for controller_cls, mod in self.registry.controller_modules.items():
			if mod == module_key:
				namespace.setdefault(controller_cls.__name__, controller_cls)

		accessible_tokens = self.registry.module_visibility.get(module_key, {})
		for token in accessible_tokens:
			if isinstance(token, type):
				namespace.setdefault(token.__name__, token)

		return namespace

	def _get_durable_context_key(
		self,
		binding: Binding,
		request: Request | None,
	) -> object:
		target = binding.target
		if isinstance(target, type) and hasattr(target, "get_durable_context_key"):
			return cast(
				object,
				getattr(target, "get_durable_context_key")(request),
			)
		if request is not None:
			return id(request)
		return "__default_durable_context__"

	def _get_cached_instance(
		self,
		binding: Binding,
		binding_key: tuple[ModuleKey, object],
		declaring_module: ModuleKey,
		token: object,
	) -> object | None:
		if binding.scope is ProviderScope.REQUEST:
			active_req = self.scope_manager.active_request.get()
			if active_req is None:
				raise ProviderResolutionError(
					f"Request-scoped provider {_qualname(token)} requires an active request"
				)
			request_cache = self.scope_manager.get_request_cache(active_req)
			return request_cache.get(binding_key)

		if binding.scope is ProviderScope.DURABLE:
			active_req = self.scope_manager.active_request.get()
			durable_key = self._get_durable_context_key(binding, active_req)
			durable_cache_key = (declaring_module, token, durable_key)
			return self.scope_manager.get_durable(durable_cache_key)

		if binding.scope is ProviderScope.SINGLETON:
			return self.scope_manager.get_singleton(binding_key)

		return None

	def _cache_instance(
		self,
		binding: Binding,
		binding_key: tuple[ModuleKey, object],
		declaring_module: ModuleKey,
		token: object,
		instance: object,
	) -> object:
		if binding.scope is ProviderScope.REQUEST:
			active_req = self.scope_manager.active_request.get()
			assert active_req is not None
			request_cache = self.scope_manager.get_request_cache(active_req)
			request_cache[binding_key] = instance
			return instance

		if binding.scope is ProviderScope.DURABLE:
			active_req = self.scope_manager.active_request.get()
			durable_key = self._get_durable_context_key(binding, active_req)
			durable_cache_key = (declaring_module, token, durable_key)
			lock = self.scope_manager.get_durable_lock(durable_cache_key)
			with lock:
				existing = self.scope_manager.get_durable(durable_cache_key)
				if existing is None:
					self.scope_manager.set_durable(durable_cache_key, instance)
				else:
					instance = existing
			return instance

		if binding.scope is ProviderScope.SINGLETON:
			lock = self.scope_manager.get_singleton_lock(binding_key)
			with lock:
				existing = self.scope_manager.get_singleton(binding_key)
				if existing is None:
					self.scope_manager.set_singleton(binding_key, instance)
				else:
					instance = existing
			return instance

		return instance

	def _is_dependency_available(self, token: object, module_key: ModuleKey) -> bool:
		visibility = self.registry.module_visibility.get(module_key, {})
		return token in visibility

	def _binding_requires_async(self, binding: Binding) -> bool:
		if binding.resolver_kind != "factory":
			return False
		factory, _inject_tokens = cast(tuple[Callable[..., object], tuple[object, ...]], binding.target)
		return inspect.iscoroutinefunction(factory)

	def _format_dependency_path(self, next_token: object) -> str:
		frames = self.resolution_stack.get()
		tokens = [frame.token for frame in frames] + [next_token]
		return " -> ".join(_display_name(token) for token in tokens)


_MISSING = object()
