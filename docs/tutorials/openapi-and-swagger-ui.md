# Letting The API Describe Itself

Somebody else has to use this shortener. Right now the only way to learn that `POST /links/` takes a
`url` and gives back a `code` is to read your source, and the only way to learn that it needs a
bearer token is to get a `401`.

An OpenAPI document fixes that, and you get most of it without writing anything, because the
framework already knows every route, its path parameters and the shape of its payload. This tutorial
turns that on, then adds the handful of things a signature cannot express.

## Turning It On

`src/my_app/app_main.py` holds the one function that builds the application, and everything that
serves it goes through there: `uv run dev`, `uv run start`, and the `client` fixture your tests
take. Describe the API inside that function and hand the description to `create_app`:

```python
from bustan import Application, DocumentBuilder, SwaggerOptions, create_app

from .app_module import AppModule


def create_asgi_app() -> Application:
    """Return the application, which is itself the ASGI callable a server runs."""
    document = (
        DocumentBuilder()
        .set_title("Link Shortener")
        .set_description("Shorten a URL, then follow the short code.")
        .set_version("1.0.0")
        .add_bearer_auth()
    )
    return create_app(
        AppModule,
        swagger=SwaggerOptions(
            document_builder=document, path="/docs/api", swagger_ui_path="/docs/ui"
        ),
    )
```

You hand over the builder, not a finished document. The framework calls it after it has compiled the
application, which is what lets the document contain routes you never listed anywhere.

`add_bearer_auth` declares that this API uses bearer tokens. It describes; it does not enforce. The
guard from the last tutorial is what enforces, and keeping the two in agreement is your job — a
document that promises an auth scheme nobody checks is worse than no document.

## Why The Document Is Not At `/api`

Most projects put it at `/api`, and if you try that here you get this:

```bash
curl -s http://127.0.0.1:3000/api
```

```json
{"type":"https://bustan.dev/problems/not-found","title":"Not Found","status":404,
 "detail":"no link with code api","instance":"/api","code":"not-found"}
```

Your own redirect controller answered. It owns `/{code}`, which matches any single path segment, so
it swallows `/api`, `/health` and every other one-segment path you might want. Read the `detail`
again: it went looking for a link with the code `api`.

This is the cost of pretty short links, and it is worth understanding rather than working around by
accident. Anything you want to serve at the root has to be more than one segment deep, or the
catch-all gets there first. Hence `/docs/api` and `/docs/ui`.

If you would rather keep `/api` free, the other option is to give short codes a prefix — `/r/{code}`
— and accept slightly longer links. Neither is wrong; pick one deliberately.

## Reading What You Got

```bash
uv run dev
```

```bash
curl -s http://127.0.0.1:3000/docs/api | uv run python -m json.tool | head -25
```

Every route this application serves is in there and nothing else is: `/health/live`,
`/health/ready`, `/links` and `/{code}`. Path parameters are typed, and the `POST` body carries the
schema Pydantic generated from `CreateLinkPayload`, including the `"format": "uri"` that says `url`
must be a URL.

None of that was written by hand. It came from the code, which means it cannot drift from the code.

Now open `http://127.0.0.1:3000/docs/ui` in a browser. Same document, as a page you can click
through and send requests from.

## Saying What The Code Cannot

What the framework cannot infer is intent. It knows `follow` hands back a response; it does not know
that response is a `302` when the code is known and a `404` when it is not, because both live inside
an `if`. Four decorators fill the gap.

In `links_controller.py`:

```python
from bustan import ApiBearerAuth, ApiOperation, ApiResponse, ApiTags


@Controller("/links")
@Auth("bearer")
@ApiTags("links")
@ApiBearerAuth()
class LinksController:

    @Post("/")
    @ApiOperation(summary="Shorten a URL")
    @ApiResponse(status=201, description="The link was created")
    @ApiResponse(status=409, description="No free code was found")
    def create_link(self, payload: CreateLinkPayload) -> HttpResponse:
        ...
```

And in `redirect_controller.py`, the two outcomes of following a code:

```python
from bustan import ApiOperation, ApiResponse, ApiTags


@Controller("/")
@Public()
@ApiTags("redirect")
class RedirectController:

    @Get("/{code}")
    @ApiOperation(summary="Follow a short code to its target")
    @ApiResponse(status=302, description="The target the code points at")
    @ApiResponse(status=404, description="No link with that code")
    def follow(self, code: str) -> HttpResponse:
        ...
```

`@ApiTags` groups routes under a heading, so the browsable page is not one long list. `@ApiOperation`
gives the human sentence a method name cannot. `@ApiResponse` documents an outcome the framework has
no way to see. `@ApiBearerAuth` marks the routes as needing the scheme you declared, which is why
the links controller has it and the redirect does not: a route anyone may call should not be
documented as wanting a token.

Document the outcomes a caller has to handle and then stop. A response entry for every status you can
imagine produces a document nobody reads.

Reload the page and the routes have descriptions.

## Testing That It Is Served

```python
def test_the_openapi_document_is_served(client: AsgiTestClient) -> None:
    document = client.get("/docs/api").json()
    assert document["info"]["title"] == "Link Shortener"
    assert "/links" in document["paths"]
```

Worth more than it looks. It fails the day somebody deletes a route and the document quietly stops
describing it, which is not a failure anyone notices by reading.

`/links` is the path in the document because `/links` is the path the route was compiled to, the
same one you have been curling since tutorial two.

## What You Have Built

Five tutorials ago you had a route that said hello. You now have a link shortener that validates what
it is given, answers the right status when things go wrong, keeps its links in a database it opens
and closes cleanly, admits when it cannot serve, refuses callers it does not recognise while leaving
short links open to everyone, and describes itself.

The finished version is [`examples/link_shortener`](../../examples/link_shortener/), and it runs on
every commit.

Where to go next depends on what you want to do with it:

- **Get it running somewhere** — [Containerise An Application](../how-to/containerise-an-application.md)
  builds an image, then [Deploy An Application](../how-to/deploy.md) covers draining, workers and
  proxies.
- **Watch it in production** — [Observe An Application](../how-to/observe-an-application.md) for
  metrics, tracing and log correlation.
- **Lock it down further** — [Harden An Application](../how-to/harden-security.md) for rate limiting,
  CORS and request size limits. An open shortener wants all three.
- **Grow the test suite** — [Test An Application](../how-to/test-an-application.md).
- **Understand what you were doing** — [Request scope](../explanation/request-scope.md) and
  [Layering](../explanation/layering.md) explain the ideas the tutorials used without dwelling on.
