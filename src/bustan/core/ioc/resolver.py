"""Recursive dependency resolution and constructor injection kernel."""

from __future__ import annotations

import inspect
import sys
import threading
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated, TypeVar, cast, get_args, get_origin, get_type_hints

import anyio

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


@dataclass(frozen=True, slots=True)
class _PlannedParameter:
	"""One constructor parameter with either a value or a pending dependency."""

	name: str
	positional: bool
	value: object = None
	dependency: ParsedDependency | None = None


@dataclass(frozen=True, slots=True)
class _ConstructionContext:
	"""Owner metadata shared by the sync and async dependency drivers."""

	owner_is_controller: bool
	is_request_scoped: bool
	active_request: Request | None


def _assemble_constructor_arguments(
	planned_parameters: tuple[_PlannedParameter, ...],
	resolved_values: list[object],
) -> tuple[tuple[object, ...], dict[str, object]]:
	positional_arguments: list[object] = []
	keyword_arguments: dict[str, object] = {}
	for planned, value in zip(planned_parameters, resolved_values, strict=True):
		if planned.positional:
			positional_arguments.append(value)
		else:
			keyword_arguments[planned.name] = value
	return tuple(positional_arguments), keyword_arguments


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
		# Classes whose constructors are currently being resolved, outermost
		# first. INQUIRER reads the entry below the class being constructed.
		self.construction_stack: ContextVar[tuple[type[object], ...]] = ContextVar(
			"bustan_construction_stack", default=()
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
			declaring_module = self._get_declaring_module(token, module)
			# Overrides are keyed by the declaring module so that overriding
			# an exported provider also takes effect when it is resolved
			# through an importing module.
			if self.override_manager.has_override(token, module=declaring_module):
				return self.override_manager.get_override(token, module=declaring_module)

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

			self._check_for_cycle(token, declaring_module)

			if binding.scope in (ProviderScope.SINGLETON, ProviderScope.DURABLE):
				# Construct shared-instance scopes under their cache lock so
				# concurrent resolution cannot build (and leak) duplicates.
				lock, store = self._shared_instance_slot(binding, binding_key, declaring_module, token)
				with lock:
					cached = self._get_cached_instance(binding, binding_key, declaring_module, token)
					if cached is not None:
						return cached
					instance = self._construct_binding(binding, token, declaring_module)
					store(instance)
					return instance

			instance = self._construct_binding(binding, token, declaring_module)
			return self._cache_instance(binding, binding_key, declaring_module, token, instance)
		finally:
			self.scope_manager.pop_request(active_request_token)

	def _construct_binding(self, binding: Binding, token: object, declaring_module: ModuleKey) -> object:
		current_stack = self.resolution_stack.get()
		stack_token = self.resolution_stack.set(
			(*current_stack, ResolutionFrame(token, declaring_module))
		)
		try:
			return self._resolve_binding(binding, module_key=declaring_module)
		finally:
			self.resolution_stack.reset(stack_token)

	async def _construct_binding_async(
		self, binding: Binding, token: object, declaring_module: ModuleKey
	) -> object:
		current_stack = self.resolution_stack.get()
		stack_token = self.resolution_stack.set(
			(*current_stack, ResolutionFrame(token, declaring_module))
		)
		try:
			return await self._resolve_binding_async(binding, module_key=declaring_module)
		finally:
			self.resolution_stack.reset(stack_token)

	def _check_for_cycle(self, token: object, declaring_module: ModuleKey) -> None:
		# A cycle exists only when the same binding identity repeats; the
		# same token name declared by two different modules is legitimate.
		current_stack = self.resolution_stack.get()
		if any(
			frame.token == token and frame.module == declaring_module
			for frame in current_stack
		):
			cycle_path = " -> ".join(
				_display_name(frame.token)
				for frame in (*current_stack, ResolutionFrame(token, declaring_module))
			)
			raise ProviderResolutionError(
				f"Circular provider dependencies detected: {cycle_path}"
			)

	def _shared_instance_slot(
		self,
		binding: Binding,
		binding_key: tuple[ModuleKey, object],
		declaring_module: ModuleKey,
		token: object,
	) -> tuple[threading.Lock, Callable[[object], None]]:
		if binding.scope is ProviderScope.DURABLE:
			active_req = self.scope_manager.active_request.get()
			durable_key = self._get_durable_context_key(binding, active_req, token)
			durable_cache_key = (declaring_module, token, durable_key)
			return (
				self.scope_manager.get_durable_lock(durable_cache_key),
				lambda instance: self.scope_manager.set_durable(durable_cache_key, instance),
			)
		return (
			self.scope_manager.get_singleton_lock(binding_key),
			lambda instance: self.scope_manager.set_singleton(binding_key, instance),
		)

	def _shared_async_construction_lock(
		self,
		binding: Binding,
		binding_key: tuple[ModuleKey, object],
		declaring_module: ModuleKey,
		token: object,
	) -> anyio.Lock:
		if binding.scope is ProviderScope.DURABLE:
			active_req = self.scope_manager.active_request.get()
			durable_key = self._get_durable_context_key(binding, active_req, token)
			return self.scope_manager.get_async_construction_lock(
				(declaring_module, token, durable_key)
			)
		return self.scope_manager.get_async_construction_lock(binding_key)

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
			declaring_module = self._get_declaring_module(token, module)
			if self.override_manager.has_override(token, module=declaring_module):
				return self.override_manager.get_override(token, module=declaring_module)

			binding_key = (declaring_module, token)
			binding = self.registry.get_binding(binding_key)
			if binding is None:
				raise ProviderResolutionError(f"Binding not found for {token!r}")

			cached = self._get_cached_instance(binding, binding_key, declaring_module, token)
			if cached is not None:
				return cached

			self._check_for_cycle(token, declaring_module)

			if binding.scope in (ProviderScope.SINGLETON, ProviderScope.DURABLE):
				# Serialize construction between tasks with an async lock; a
				# threading lock held across an await could freeze the loop.
				async_lock = self._shared_async_construction_lock(
					binding, binding_key, declaring_module, token
				)
				async with async_lock:
					cached = self._get_cached_instance(binding, binding_key, declaring_module, token)
					if cached is not None:
						return cached
					instance = await self._construct_binding_async(binding, token, declaring_module)
					return self._cache_instance(binding, binding_key, declaring_module, token, instance)

			instance = await self._construct_binding_async(binding, token, declaring_module)
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
				binding_scope=binding.scope,
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
			return await self.instantiate_class_async(
				cls_target,
				module=module_key,
				request=self.scope_manager.active_request.get(),
				binding_scope=binding.scope,
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
		binding_scope: ProviderScope | None = None,
	) -> object:
		"""Resolve a fresh controller or class instance for request handling."""

		active_request_token = self.scope_manager.push_request(request)
		try:
			positional_arguments, keyword_arguments = self._resolve_constructor_dependencies(
				cls,
				module,
				binding_scope=binding_scope,
			)
			return cls(*positional_arguments, **keyword_arguments)
		finally:
			self.scope_manager.pop_request(active_request_token)

	async def instantiate_class_async(
		self,
		cls: type[object],
		*,
		module: ModuleKey,
		request: Request | None = None,
		binding_scope: ProviderScope | None = None,
	) -> object:
		"""Instantiate a class while awaiting async constructor dependencies."""

		active_request_token = self.scope_manager.push_request(request)
		try:
			positional_arguments, keyword_arguments = (
				await self._resolve_constructor_dependencies_async(
					cls,
					module,
					binding_scope=binding_scope,
				)
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
		binding_scope: ProviderScope | None = None,
	) -> tuple[tuple[object, ...], dict[str, object]]:
		construction_token = self.construction_stack.set(
			(*self.construction_stack.get(), class_cls)
		)
		try:
			planned_parameters, context = self._plan_constructor_parameters(
				class_cls,
				module_key,
				binding_scope,
			)
			resolved_values: list[object] = []
			for planned in planned_parameters:
				if planned.dependency is None:
					resolved_values.append(planned.value)
					continue
				resolved_values.append(
					self._resolve_declared_dependency(
						planned.dependency,
						class_cls=class_cls,
						parameter_name=planned.name,
						module_key=module_key,
						owner_is_controller=context.owner_is_controller,
						is_request_scoped=context.is_request_scoped,
						active_request=context.active_request,
					)
				)
			return _assemble_constructor_arguments(planned_parameters, resolved_values)
		finally:
			self.construction_stack.reset(construction_token)

	async def _resolve_constructor_dependencies_async(
		self,
		class_cls: type[object],
		module_key: ModuleKey,
		binding_scope: ProviderScope | None = None,
	) -> tuple[tuple[object, ...], dict[str, object]]:
		construction_token = self.construction_stack.set(
			(*self.construction_stack.get(), class_cls)
		)
		try:
			planned_parameters, context = self._plan_constructor_parameters(
				class_cls,
				module_key,
				binding_scope,
			)
			resolved_values: list[object] = []
			for planned in planned_parameters:
				if planned.dependency is None:
					resolved_values.append(planned.value)
					continue
				resolved_values.append(
					await self._resolve_declared_dependency_async(
						planned.dependency,
						class_cls=class_cls,
						parameter_name=planned.name,
						module_key=module_key,
						owner_is_controller=context.owner_is_controller,
						is_request_scoped=context.is_request_scoped,
						active_request=context.active_request,
					)
				)
			return _assemble_constructor_arguments(planned_parameters, resolved_values)
		finally:
			self.construction_stack.reset(construction_token)

	def _plan_constructor_parameters(
		self,
		class_cls: type[object],
		module_key: ModuleKey,
		binding_scope: ProviderScope | None,
	) -> tuple[tuple[_PlannedParameter, ...], _ConstructionContext]:
		owner_is_controller = class_cls in self.registry.controller_modules
		if binding_scope is not None:
			is_request_scoped = binding_scope is ProviderScope.REQUEST
			is_durable_scoped = binding_scope is ProviderScope.DURABLE
		else:
			is_request_scoped, is_durable_scoped = self._detect_owner_scope(class_cls)

		context = _ConstructionContext(
			owner_is_controller=owner_is_controller,
			is_request_scoped=is_request_scoped,
			active_request=self.scope_manager.active_request.get(),
		)

		constructor = class_cls.__init__
		if constructor is object.__init__:
			return (), context

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

		planned_parameters: list[_PlannedParameter] = []
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

			positional = parameter.kind in (
				inspect.Parameter.POSITIONAL_ONLY,
				inspect.Parameter.POSITIONAL_OR_KEYWORD,
			)
			dependency = self._parse_dependency(annotation)
			resolved = self._resolve_special_token(
				dependency,
				class_cls=class_cls,
				parameter_name=parameter.name,
				active_request=context.active_request,
				owner_is_controller=owner_is_controller,
				is_request_scoped=is_request_scoped,
				is_durable_scoped=is_durable_scoped,
			)
			if resolved is not _MISSING:
				planned_parameters.append(
					_PlannedParameter(name=parameter.name, positional=positional, value=resolved)
				)
			elif dependency.optional and not self._is_dependency_available(dependency.token, module_key):
				planned_parameters.append(
					_PlannedParameter(name=parameter.name, positional=positional, value=None)
				)
			else:
				planned_parameters.append(
					_PlannedParameter(
						name=parameter.name,
						positional=positional,
						dependency=dependency,
					)
				)

		return tuple(planned_parameters), context

	def _detect_owner_scope(self, class_cls: type[object]) -> tuple[bool, bool]:
		for binding in self.registry.bindings.values():
			if binding.resolver_kind == "class" and binding.target is class_cls:
				if binding.scope is ProviderScope.REQUEST:
					return True, False
				if binding.scope is ProviderScope.DURABLE:
					return False, True
				break
		return False, False

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
		self._guard_request_scoped_dependency(
			dependency,
			class_cls=class_cls,
			parameter_name=parameter_name,
			module_key=module_key,
			owner_is_controller=owner_is_controller,
			is_request_scoped=is_request_scoped,
		)
		try:
			return self.resolve(dependency.token, module=module_key, request=active_request)
		except ProviderResolutionError as exc:
			raise self._declared_dependency_error(
				dependency, class_cls, parameter_name, module_key, exc
			) from exc

	async def _resolve_declared_dependency_async(
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
		self._guard_request_scoped_dependency(
			dependency,
			class_cls=class_cls,
			parameter_name=parameter_name,
			module_key=module_key,
			owner_is_controller=owner_is_controller,
			is_request_scoped=is_request_scoped,
		)
		try:
			return await self.resolve_async(
				dependency.token, module=module_key, request=active_request
			)
		except ProviderResolutionError as exc:
			raise self._declared_dependency_error(
				dependency, class_cls, parameter_name, module_key, exc
			) from exc

	def _guard_request_scoped_dependency(
		self,
		dependency: ParsedDependency,
		*,
		class_cls: type[object],
		parameter_name: str,
		module_key: ModuleKey,
		owner_is_controller: bool,
		is_request_scoped: bool,
	) -> None:
		if isinstance(dependency.annotation, str):
			return

		dependency_declaring_module = self.registry.module_visibility.get(module_key, {}).get(
			dependency.token
		)
		if dependency_declaring_module is None:
			return

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

	def _declared_dependency_error(
		self,
		dependency: ParsedDependency,
		class_cls: type[object],
		parameter_name: str,
		module_key: ModuleKey,
		exc: ProviderResolutionError,
	) -> ProviderResolutionError:
		return ProviderResolutionError(
			f"{_qualname(class_cls)}.__init__ parameter {parameter_name!r} in "
			f"{_display_name(module_key)} failed to resolve {_qualname(dependency.token)} "
			f"(dependency path: {self._format_dependency_path(dependency.token)}): {exc}"
		)

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
			# The class currently being constructed sits on top of the
			# construction stack; its inquirer is the entry below it.
			construction_stack = self.construction_stack.get()
			if len(construction_stack) < 2:
				raise ProviderResolutionError(
					f"{_qualname(class_cls)}.__init__ parameter {parameter_name!r} requested INQUIRER, "
					"which is only available during nested provider resolution"
				)
			return construction_stack[-2]

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
		token: object,
	) -> object:
		target = binding.target
		if isinstance(target, type) and hasattr(target, "get_durable_context_key"):
			return cast(
				object,
				getattr(target, "get_durable_context_key")(request),
			)
		# A durable instance cache must never be keyed on id(request):
		# CPython reuses object ids, which hands one request's instance to a
		# later, unrelated request. Partitioning requires an explicit key.
		raise ProviderResolutionError(
			f"Durable provider {_qualname(token)} must implement the DurableProvider "
			"protocol with a 'get_durable_context_key' classmethod so durable "
			"instances can be partitioned across requests"
		)

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
			durable_key = self._get_durable_context_key(binding, active_req, token)
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
			durable_key = self._get_durable_context_key(binding, active_req, token)
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
