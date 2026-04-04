# Routing And Parameter Binding

`star` compiles controller handlers into Starlette routes. Route decorators stay close to the handler, while the controller prefix supplies the shared path segment.

## Route Declaration

```python
from star import controller, get, post


@controller("/users")
class UsersController:
    @get("/")
    def list_users(self) -> list[dict[str, str]]:
        return [{"name": "Ada"}]

    @get("/{user_id}")
    def read_user(self, user_id: int) -> dict[str, int]:
        return {"user_id": user_id}

    @post("/")
    def create_user(self, payload: dict) -> dict:
        return payload
```

## Binding Rules

- `Request` parameters are injected directly from Starlette.
- Path parameters bind by name from the route path.
- Query parameters bind by name for inferred scalar and list parameters.
- JSON request bodies bind to a single inferred parameter, or by field name when multiple inferred parameters are present.
- Query values win over JSON body values for inferred scalars so callers can override simple inputs without reshaping the body.

## Common Shapes

```python
from dataclasses import dataclass

from starlette.requests import Request


@dataclass(frozen=True, slots=True)
class CreateUserPayload:
    name: str
    admin: bool


@controller("/users")
class UsersController:
    @get("/{user_id}")
    def read_user(
        self,
        request: Request,
        user_id: int,
        verbose: bool = False,
        page: int = 1,
    ) -> dict[str, object]:
        return {
            "path": request.url.path,
            "user_id": user_id,
            "verbose": verbose,
            "page": page,
        }

    @post("/")
    def create_user(self, payload: CreateUserPayload) -> dict[str, object]:
        return {"name": payload.name, "admin": payload.admin}
```

## Response Behavior

- Returning a Starlette `Response` sends it through untouched.
- Returning `dict`, `list`, or dataclass values produces JSON responses.
- Returning `None` produces an empty `204 No Content` response.

## Failure Modes

- Invalid path, query, or body conversions raise `ParameterBindingError` and become HTTP `400` unless an exception filter handles them.
- When multiple handler parameters need data from the request body, the body must be a JSON object.
- Variadic handler parameters such as `*args` and `**kwargs` are rejected during route compilation.