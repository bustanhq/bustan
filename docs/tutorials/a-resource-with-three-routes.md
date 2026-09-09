# Shorten Your First Link

You finished [Your First App](first-app.md), so you have a project that answers one route with a
greeting. In this tutorial you turn it into something you would actually use: a link shortener.

Here is what it will do by the end. You send it a long URL:

```bash
curl -X POST http://127.0.0.1:3000/links/ \
  -H 'content-type: application/json' \
  -d '{"url": "https://docs.python.org/3/library/sqlite3.html"}'
```

It hands you back a short code:

```json
{"code":"k3m9x2","url":"https://docs.python.org/3/library/sqlite3.html","visits":0}
```

And visiting that code sends you to the real page:

```bash
curl -i http://127.0.0.1:3000/k3m9x2
```

```text
HTTP/1.1 302 Found
location: https://docs.python.org/3/library/sqlite3.html
```

We will build it in small pieces, running it after each one. If you would rather read the finished
code, it is in [`examples/link_shortener`](../../examples/link_shortener/), and it runs in CI, so
where it and this page disagree it is the one to trust. Its package is `link_shortener` and yours is
`my_app`.

## Storing One Link

Start with the smallest thing that could work: somewhere to put links, and a way to make a code.

Create `src/my_app/links_service.py`:

```python
from __future__ import annotations

import secrets
import string

from bustan import Injectable

ALPHABET = string.ascii_lowercase + string.digits


@Injectable()
class LinksService:
    def __init__(self) -> None:
        self._links: dict[str, str] = {}

    def create_link(self, url: str) -> str:
        code = "".join(secrets.choice(ALPHABET) for _ in range(6))
        self._links[code] = url
        return code

    def read_link(self, code: str) -> str | None:
        return self._links.get(code)
```

A dictionary, for now. Tutorial four swaps it for a real database and this class is the only one
that changes, which is most of the reason it exists.

`@Injectable()` is what tells the framework this class can be handed to anything that asks for it.
You will not write `LinksService()` anywhere; you ask for one and it arrives.

## Handing Out Codes

Now a route to call it. Create `src/my_app/links_controller.py`:

```python
from __future__ import annotations

from bustan import Controller, Post

from .links_service import LinksService


@Controller("/links")
class LinksController:
    def __init__(self, links: LinksService) -> None:
        self._links = links

    @Post("/")
    def create_link(self, payload: dict) -> dict[str, str]:
        code = self._links.create_link(payload["url"])
        return {"code": code}
```

That constructor is the injection. You declared `links: LinksService`, and because `LinksService` is
`@Injectable()` the framework builds one and passes it in. You never wire it up by hand.

Register the controller and the service in `src/my_app/app_module.py`:

```python
from bustan import Module

from .links_controller import LinksController
from .links_service import LinksService


@Module(controllers=[LinksController], providers=[LinksService])
class AppModule:
    pass
```

Run it:

```bash
uv run dev
```

```bash
curl -X POST http://127.0.0.1:3000/links/ \
  -H 'content-type: application/json' \
  -d '{"url": "https://example.com"}'
```

```json
{"code":"7fq2ba"}
```

You have a shortener that shortens. It does not yet do the useful half.

## Making The Code Go Somewhere

A short link nobody can follow is just a string. Add a second controller, at the root this time, so
the code sits directly after the domain.

Create `src/my_app/redirect_controller.py`:

```python
from __future__ import annotations

from bustan import Controller, Get, HttpResponse

from .links_service import LinksService


@Controller("/")
class RedirectController:
    def __init__(self, links: LinksService) -> None:
        self._links = links

    @Get("/{code}")
    def follow(self, code: str) -> HttpResponse:
        url = self._links.read_link(code)
        return HttpResponse(status_code=302, headers={"location": url})
```

Two things to notice. `{code}` in the path and `code: str` on the method line up by name, and that
is how the value gets in. And this controller asks for the same `LinksService` the other one does,
and gets the same instance, which is why a code created by one is visible to the other.

Add it to the module's `controllers` list, restart, and try it:

```bash
curl -X POST http://127.0.0.1:3000/links/ -H 'content-type: application/json' \
  -d '{"url": "https://bustan.dev"}'
```

```json
{"code":"m1p8kd"}
```

```bash
curl -i http://127.0.0.1:3000/m1p8kd
```

```text
HTTP/1.1 302 Found
location: https://bustan.dev
```

Paste that short URL into a browser and it takes you there. That is the whole product, in about
forty lines.

## What Happens When The Code Is Wrong

Try a code that was never created:

```bash
curl -i http://127.0.0.1:3000/nope
```

You get a `500`. Look at the terminal running the server and you will see why: `read_link` returned
`None`, and `HttpResponse` was handed `location: None`.

The fix is to say what actually happened. A code nobody created is not a server error; it is a
missing thing, and HTTP has a status for that.

```python
from bustan.errors import NotFoundException


    @Get("/{code}")
    def follow(self, code: str) -> HttpResponse:
        url = self._links.read_link(code)
        if url is None:
            raise NotFoundException(f"no link with code {code}")
        return HttpResponse(status_code=302, headers={"location": url})
```

```bash
curl -i http://127.0.0.1:3000/nope
```

```text
HTTP/1.1 404 Not Found
content-type: application/problem+json

{"type":"https://bustan.dev/problems/not-found","title":"Not Found","status":404,
 "detail":"no link with code nope","instance":"/nope","code":"not-found"}
```

You raised an exception and got a structured error document. That is the framework's error contract:
every refusal it makes comes back in this shape, so a client can handle all of them with one piece
of code instead of guessing per endpoint. `bustan.errors` has one of these for each status you would
reasonably answer with, and [the error reference](../reference/errors.md) lists them.

One tempting alternative is worth naming so you do not reach for it. If `follow` returned `None`
instead of raising, you would get a `204 No Content` — which tells the caller "there is nothing to
send", not "there is no such link". Both look fine in a browser and only one of them is true.

## What Happens When The URL Is Rubbish

Now the other end:

```bash
curl -X POST http://127.0.0.1:3000/links/ -H 'content-type: application/json' \
  -d '{"url": "not a url at all"}'
```

It cheerfully creates a link. Whoever clicks it finds out.

The handler takes `payload: dict`, which accepts anything shaped like JSON. Describe what you
actually want instead, and the framework checks it before your code runs.

```bash
uv add pydantic
```

Pydantic is not part of the `starlette` extra, so you install it yourself. Create
`src/my_app/models.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, HttpUrl


class CreateLinkPayload(BaseModel):
    url: HttpUrl
```

Then annotate the handler with it:

```python
from .models import CreateLinkPayload


    @Post("/")
    def create_link(self, payload: CreateLinkPayload) -> dict[str, str]:
        code = self._links.create_link(str(payload.url))
        return {"code": code}
```

That is the whole change. A parameter annotated with a Pydantic model is validated on the way in:

```bash
curl -i -X POST http://127.0.0.1:3000/links/ -H 'content-type: application/json' \
  -d '{"url": "not a url at all"}'
```

```text
HTTP/1.1 400 Bad Request
content-type: application/problem+json
```

The body carries an `errors` array, and each entry names the field and where it came from. Same
shape as the `404`. Your handler never ran.

## Answering 201 Instead Of 200

One detail left. Creating something should answer `201 Created` and say where the new thing lives,
and right now you answer `200`.

Returning a plain dictionary means "here is the body, use the default status". To control the
status, return a response instead:

```python
from bustan import HttpResponse


    @Post("/")
    def create_link(self, payload: CreateLinkPayload) -> HttpResponse:
        code = self._links.create_link(str(payload.url))
        return HttpResponse.json(
            {"code": code}, status_code=201, headers={"location": f"/links/{code}"}
        )
```

```bash
curl -i -X POST http://127.0.0.1:3000/links/ -H 'content-type: application/json' \
  -d '{"url": "https://example.com"}'
```

```text
HTTP/1.1 201 Created
location: /links/6bd0zq
```

## Tidying Up Into A Module

You now have two controllers and a service all declared in the root module. That works, and it stops
working the moment the application grows. Group them.

Move the three files into `src/my_app/links/` with an empty `__init__.py`, fix the imports, and add
`src/my_app/links/links_module.py`:

```python
from __future__ import annotations

from bustan import Module

from .links_controller import LinksController
from .links_service import LinksService
from .redirect_controller import RedirectController


@Module(
    controllers=[LinksController, RedirectController],
    providers=[LinksService],
    exports=[LinksService],
)
class LinksModule:
    pass
```

Then the root module just imports it:

```python
@Module(imports=[LinksModule])
class AppModule:
    pass
```

`exports` is the part worth understanding. A module's providers are private to it by default. Listing
`LinksService` in `exports` says that anything importing `LinksModule` may inject it; everything else
inside stays unreachable. That is what makes a module a boundary rather than a folder, and you will
feel it in tutorial four when a module that forgets an import refuses to start.

Restart and check both routes still work. Nothing about the behaviour changed; you moved code.

## Writing The Tests

Three things this tutorial promised, three tests. Create `tests/my_app/test_links.py`:

```python
from bustan.testing import AsgiTestClient
from my_app import build_application


def test_shortening_a_url_returns_201() -> None:
    with AsgiTestClient(build_application()) as client:
        response = client.post("/links/", json={"url": "https://example.com/a"})

    assert response.status_code == 201


def test_following_a_code_redirects_to_the_target() -> None:
    with AsgiTestClient(build_application()) as client:
        code = client.post("/links/", json={"url": "https://example.com/b"}).json()["code"]
        response = client.get(f"/{code}", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "https://example.com/b"


def test_an_unknown_code_returns_404() -> None:
    with AsgiTestClient(build_application()) as client:
        response = client.get("/nothing-here", follow_redirects=False)

    assert response.status_code == 404
```

`AsgiTestClient` ships with the framework, so there is no HTTP client to install and no server to
start. `follow_redirects=False` matters in the second test: without it the client would chase the
redirect to example.com and you would be asserting on their response, not yours.

```bash
uv run pytest
```

Three tests, and each one is a sentence from the top of this page.

## Where This Leaves You

A working shortener with correct statuses, validated input and a real error contract. Two things are
still wrong with it, and you can probably feel both.

Restart the server and every link you made is gone, because they live in a dictionary. And the code
length, which decides how many links you can have before collisions, is a `6` buried in a method.

The next tutorial deals with the second one, and the one after that with the first:
[Settings That Live Outside The Code](configuration-end-to-end.md).
