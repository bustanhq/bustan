"""Unit tests for compiled handler binding plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import pytest

from bustan import Body, Controller, Get, Post, Query
from bustan.core.errors import ParameterBindingError
from bustan.platform.http.metadata import iter_controller_routes
from bustan.platform.http.params import (
    ParameterBindingMode,
    ParameterSource,
    ValidationMode,
    compile_parameter_bindings,
)


@dataclass(frozen=True, slots=True)
class CreateUserPayload:
    name: str
    admin: bool


def test_binding_plans_preserve_parameter_order_and_source_location() -> None:
    @Controller("/users", binding_mode="infer")
    class UsersController:
        @Post("/{user_id}")
        def update_user(
            self,
            user_id: int,
            version: Annotated[int, Query],
            payload: Annotated[CreateUserPayload, Body],
        ) -> None:
            return None

    route_definition = iter_controller_routes(UsersController)[0]

    binding_plan = compile_parameter_bindings(UsersController, route_definition)

    assert [binding.name for binding in binding_plan.parameters] == ["user_id", "version", "payload"]
    assert [binding.source for binding in binding_plan.parameters] == [
        ParameterSource.PATH,
        ParameterSource.QUERY,
        ParameterSource.BODY,
    ]
    assert binding_plan.mode is ParameterBindingMode.INFER
    assert binding_plan.validation_mode is ValidationMode.AUTO


def test_strict_mode_rejects_ambiguous_parameters_at_startup() -> None:
    @Controller("/users", binding_mode="strict")
    class UsersController:
        @Get("/")
        def list_users(self, page: int) -> None:
            return None

    route_definition = iter_controller_routes(UsersController)[0]

    with pytest.raises(ParameterBindingError, match="strict mode"):
        compile_parameter_bindings(UsersController, route_definition)


def test_infer_mode_resolves_query_and_body_sources_from_http_method_heuristics() -> None:
    @Controller("/users", binding_mode="infer")
    class UsersController:
        @Get("/{user_id}")
        def read_user(self, user_id: int, page: int = 1) -> None:
            return None

        @Post("/")
        def create_user(self, payload: CreateUserPayload) -> None:
            return None

    read_route, create_route = iter_controller_routes(UsersController)

    read_plan = compile_parameter_bindings(UsersController, read_route)
    create_plan = compile_parameter_bindings(UsersController, create_route)

    assert [binding.source for binding in read_plan.parameters] == [
        ParameterSource.PATH,
        ParameterSource.QUERY,
    ]
    assert [binding.source for binding in create_plan.parameters] == [ParameterSource.BODY]
    assert create_plan.inferred_parameter_names == ("payload",)
    assert create_plan.body_model is CreateUserPayload