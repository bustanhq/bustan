# Routing And Parameter Binding

`Bustan` compiles controller classes into adapter routes. The controller prefix defines the shared path segment, the handler decorator defines the HTTP method and suffix, and handler parameters are turned into a binding plan at startup.

## Declare Routes Near The Handler

```python
from bustan import Controller, Get, Post


@Controller("/users")
class UsersController:
    @Get("/")
    def list_users(self) -> list[dict[str, str]]:
        return [{"name": "Ada"}]

    @Get("/{user_id}")
    def read_user(self, user_id: int) -> dict[str, int]:
        return {"user_id": user_id}

    @Post("/")
    def create_user(self, payload: dict[str, object]) -> dict[str, object]:
        return payload
```

By default controllers are singleton-scoped. Bustan reuses the same controller instance across requests unless you opt into request scope on the controller.

## Inferred Binding Rules

When you do not use explicit binding markers, Bustan infers a source from the parameter shape:

- `starlette.requests.Request` injects the native Starlette request object.
- `bustan.HttpRequest` injects the adapter-neutral request wrapper.
- Path parameters bind by name from the route pattern.
- Query parameters bind by name for inferred scalar and list values.
- A single structured parameter such as a dataclass or Pydantic model binds from the JSON request body.
- When multiple inferred parameters need body data, Bustan expects a JSON object and binds fields by name.
- For inferred scalar values, query parameters win over JSON body fields with the same name.

Example:

```python
from dataclasses import dataclass

from bustan import Controller, Get, Post
from bustan.platform.http.abstractions import HttpRequest


@dataclass(frozen=True, slots=True)
class CreateUserPayload:
    name: str
    admin: bool


@Controller("/users")
class UsersController:
    @Get("/{user_id}")
    def read_user(
        self,
        request: HttpRequest,
        user_id: int,
        verbose: bool = False,
        page: int = 1,
    ) -> dict[str, object]:
        return {
            "path": request.path,
            "user_id": user_id,
            "verbose": verbose,
            "page": page,
        }

    @Post("/")
    def create_user(self, payload: CreateUserPayload) -> dict[str, object]:
        return {"name": payload.name, "admin": payload.admin}
```

## Use Explicit Binding Markers With `Annotated`

When inference is not specific enough, use `typing.Annotated` plus the public marker helpers from `bustan`.

```python
from typing import Annotated

from bustan import Body, Controller, Get, Header, Param, Post, Query


@Controller("/users", validation_mode="auto")
class UsersController:
    @Get("/{user_id}")
    def read_user(
        self,
        user_id: Annotated[int, Param],
        search: Annotated[str | None, Query("q")] = None,
        api_token: Annotated[str, Header("X-API-Token")] = "",
    ) -> dict[str, object]:
        return {
            "user_id": user_id,
            "search": search,
            "has_token": bool(api_token),
        }

    @Post("/")
    def create_user(self, payload: Annotated[CreateUserPayload, Body]) -> dict[str, object]:
        return {"name": payload.name, "admin": payload.admin}
```

Common markers:

- `Param` for path parameters.
- `Query` for query-string values.
- `Body` for JSON body input.
- `Header` for headers. When you omit an alias, underscores convert to hyphens.
- `Cookies` for one cookie value or the full cookie mapping.
- `HostParam` for the host header or forwarded-host style aliases.
- `Ip` for the resolved client IP.
- `UploadedFile` and `UploadedFiles` for multipart file input.

## Binding And Validation Modes

Two controller-level options matter when you want tighter request contracts:

- `binding_mode="strict"` rejects ambiguous inferred parameters at startup instead of guessing.
- `validation_mode="auto"` appends `ValidationPipe` automatically for supported Pydantic models when you have not already added one.

Use strict mode when handler signatures must be explicit and startup-time failure is preferable to runtime ambiguity.

## Response Coercion

Handlers can return several common shapes directly:

- Starlette `Response` instances pass through untouched.
- `bustan.HttpResponse` passes through untouched.
- `dict`, `list`, and dataclass instances become JSON responses.
- `None` becomes `204 No Content`.
- `Iterator[bytes]` becomes a streaming response.
- `pathlib.Path` becomes a file response.

Example:

```python
from pathlib import Path
from collections.abc import Iterator

from starlette.responses import PlainTextResponse

from bustan import Controller, Get
from bustan.platform.http.abstractions import HttpResponse


@Controller("/responses")
class ResponseController:
    @Get("/plain")
    def read_plain(self) -> PlainTextResponse:
        return PlainTextResponse("ok", status_code=202)

    @Get("/json")
    def read_json(self) -> HttpResponse:
        return HttpResponse.json({"status": "ok"}, status_code=203)

    @Get("/stream")
    def read_stream(self) -> Iterator[bytes]:
        yield b"hello"
        yield b" "
        yield b"stream"

    @Get("/file")
    def read_file(self) -> Path:
        return Path("./status.txt")
```

## Failure Modes

- Conversion errors raise `ParameterBindingError` and become HTTP `400` unless an exception filter handles them.
- Missing required headers, path parameters, or body fields surface as structured binding errors.
- When multiple parameters read from the body, the request body must be a JSON object.
- Variadic handler parameters such as `*args` and `**kwargs` are rejected during route compilation.

Continue with [REQUEST_PIPELINE.md](REQUEST_PIPELINE.md) after the route shape is clear. Routing determines what values are available; the pipeline determines how those values are validated, transformed, or rejected.