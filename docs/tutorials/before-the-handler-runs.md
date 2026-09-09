# Deciding Who May Create A Link

Your shortener is open to the world. Anyone who finds it can point a short code at anything, which is
how open shorteners become spam relays.

Two different jobs need doing before a handler runs, and the framework has a different stage for
each. This tutorial does both, in the order they happen, because putting one in the other's place is
the mistake worth avoiding.

## Something That Happens To Every Request

Start with the simpler job. When something goes wrong you want to trace one request through your
logs, which means every request needs an id, and the caller needs to see it so they can quote it.

That work is genuinely universal: it applies to every route, and it does not care which handler is
about to run. Middleware is the stage for exactly that, and it runs first, before routing has chosen
anything.

Create `src/my_app/request_id_middleware.py`:

```python
from __future__ import annotations

from uuid import uuid4

from bustan import HttpRequest, Middleware


class RequestIdMiddleware(Middleware):
    async def use(self, request: HttpRequest, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid4())
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response
```

`call_next` is the rest of the application. Everything before that line happens on the way in,
everything after it on the way out, which is why middleware can touch the response as well as the
request. Honouring an incoming `x-request-id` matters if anything sits in front of you, so a trace
started at your load balancer continues here rather than restarting.

Register it from the root module by implementing `configure`:

```python
from bustan import MiddlewareConsumer

from .request_id_middleware import RequestIdMiddleware


class AppModule:
    def configure(self, consumer: MiddlewareConsumer) -> None:
        consumer.apply(RequestIdMiddleware).exclude("/health/live", "/health/ready")
```

The probes are excluded because a load balancer hits them every few seconds and a correlation id on a
liveness check correlates nothing.

```bash
uv run dev
curl -si http://127.0.0.1:3000/links/ | grep -i x-request-id
```

```text
x-request-id: 4e8f1a90-2c31-4b7e-9a55-1f0c7b3d2a64
```

Ask again and the id changes. Send your own and it comes back unchanged.

## Something That Depends On Which Route Was Chosen

Now the harder job. Creating a link should need permission; following one should not, because a short
link nobody can click is not a short link.

That is a per-route decision, and middleware cannot make it. Middleware runs before routing, so it
does not know which handler is coming, which means it cannot know whether this particular route is
public. You would end up matching on URL patterns inside your middleware, re-implementing the router
badly.

The stage that runs after routing, and knows the handler, is a guard. The framework already ships the
guard that enforces policy; what it cannot know is how *your* application decides who a caller is.
That is the piece you write.

Which stage a job belongs in is a recurring question, and
[Choose A Pipeline Hook](../how-to/choose-a-pipeline-hook.md) is the short answer for all of them.

## Saying Who The Caller Is

Add a token to `Settings` and `.env`:

```python
    API_TOKEN: str = Field(min_length=8)
```

```bash
API_TOKEN=a-long-local-development-token
```

Create `src/my_app/bearer_authenticator.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from bustan import ConfigService, ExecutionContext, Injectable


@dataclass(frozen=True, slots=True)
class TokenPrincipal:
    id: str
    roles: tuple[str, ...]
    permissions: tuple[str, ...]


@Injectable()
class BearerAuthenticator:
    def __init__(self, config: ConfigService) -> None:
        self._token = str(config.get_or_throw("API_TOKEN"))

    def authenticate(self, context: ExecutionContext) -> TokenPrincipal | None:
        request = context.request
        header = "" if request is None else request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or token != self._token:
            return None
        return TokenPrincipal(id="local", roles=("editor",), permissions=())
```

You return a principal or you return `None`. You never write a status code: returning `None` is the
refusal, and the guard turns it into `401`.

`TokenPrincipal` is an ordinary dataclass. The framework asks for an `id`, `roles` and `permissions`,
and anything with those three attributes qualifies, so you are not inheriting from anything.

Comparing one shared token is this tutorial's shortcut. A real authenticator verifies a signed token
or asks an identity provider, and every line around it stays the same.

## Telling The Framework Which Strategy Is Which

A route will ask for authentication by name — `@Auth("bearer")` — and something has to map that name
to your class. Create `src/my_app/identity_module.py`:

```python
from __future__ import annotations

from bustan import AUTHENTICATOR_REGISTRY, FactoryProvider, Module

from .bearer_authenticator import BearerAuthenticator


def _registry(authenticator: BearerAuthenticator) -> dict[str, object]:
    return {"bearer": authenticator}


@Module(
    providers=[
        BearerAuthenticator,
        FactoryProvider(
            provide=AUTHENTICATOR_REGISTRY,
            use_factory=_registry,
            inject=(BearerAuthenticator,),
        ),
    ],
    exports=[AUTHENTICATOR_REGISTRY],
)
class IdentityModule:
    pass
```

That provider is written as a `FactoryProvider` rather than a class because what you are providing
is a value built from other things: a factory function, and the list of what to inject into it. It
is the same idea as `@Injectable()`, spelled out for the cases where there is no class to decorate.

## Guarding The Routes

In `links_controller.py`:

```python
from bustan import Auth


@Controller("/links")
@Auth("bearer")
class LinksController:
    ...
```

And in `redirect_controller.py`, the opposite:

```python
from bustan import Public


@Controller("/")
@Public()
class RedirectController:
    ...
```

`@Auth` on a class covers every route in it. `@Public` says this one is deliberately open, which is
worth stating rather than leaving to the absence of a decorator — a reader can tell the difference
between "open on purpose" and "somebody forgot".

## The Refusal Worth Causing On Purpose

Start the application now, before adding any import to `LinksModule`.

```text
LinksController.list_links authenticates its callers, and no provider for
AUTHENTICATOR_REGISTRY is visible to LinksModule. Declare one in that module, or
import a module that exports it
```

It refuses to start, and this is the framework at its most useful. A route that asks for
authentication it cannot perform is a defect, and the choice is between finding out now or finding
out when a caller does. It checks while routes compile, and names the handler and the module.

It is the same shape as the store refusal in the last tutorial, and the same fix. Add
`IdentityModule` to `LinksModule`'s imports, and to the root module's.

## Try Both Sides

```bash
curl -si -X POST http://127.0.0.1:3000/links/ -H 'content-type: application/json' \
  -d '{"url":"https://example.com"}' | head -1
```

```text
HTTP/1.1 401 Unauthorized
```

```bash
curl -si -X POST http://127.0.0.1:3000/links/ \
  -H 'authorization: Bearer a-long-local-development-token' \
  -H 'content-type: application/json' -d '{"url":"https://example.com"}' | head -1
```

```text
HTTP/1.1 201 Created
```

And the short link still works with no token at all, which was the point:

```bash
curl -si http://127.0.0.1:3000/<your-code> | head -1
```

```text
HTTP/1.1 302 Found
```

`401` means the application does not know who you are. `403` means it knows and you still may not.
Sending `403` for an unauthenticated request is a common mix-up and it tells an attacker more than
you meant to; [Harden An Application](../how-to/harden-security.md#401-versus-403) has the rule.

## Test The Refusal, Not Just The Success

Add a `token` fixture to `conftest.py`:

```python
@pytest.fixture
def token() -> dict[str, str]:
    return {"authorization": "Bearer a-long-local-development-token"}
```

Then give the existing tests that header, and add these:

```python
def test_creating_a_link_needs_a_token(client: AsgiTestClient) -> None:
    assert client.post("/links/", json={"url": "https://example.com"}).status_code == 401


def test_following_a_link_needs_no_token(client, token) -> None:
    client.post("/links/", headers=token, json={"url": "https://example.com", "code": "open"})
    assert client.get("/open", follow_redirects=False).status_code == 302


def test_every_response_carries_a_request_id(client, token) -> None:
    assert client.get("/links/", headers=token).headers["x-request-id"]
```

The first of those is the one people skip. A guard that is never seen refusing anything in a test is
a guard nobody has checked, and a guard that stops working fails silently and permissively.

## Where This Leaves You

Every response is traceable, creating links needs a token, and following one does not.

The API works and nothing describes it, which is the last thing:
[Letting The API Describe Itself](openapi-and-swagger-ui.md).
