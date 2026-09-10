# Read A Value The Binders Do Not Cover

`Param`, `Query`, `Header` and `Body` reach the usual places a handler argument
comes from. When you want something they do not — a value assembled from several
headers, something a guard left on the request, a decoded token — write a marker
of your own with `create_param_decorator`.

It takes one function. That function receives the decorator's own argument and
the execution context, and returns whatever the handler should be given.

```python
from typing import Annotated

from bustan import Controller, Get, create_param_decorator

UserAgent = create_param_decorator(
    lambda data, context: context.switch_to_http()
    .get_request()
    .headers.get("user-agent", "")
)


@Controller("/c")
class CController:
    @Get("/")
    def read(self, ua: Annotated[str, UserAgent()]) -> dict[str, str]:
        return {"ua": ua}
```

```bash
curl -H 'User-Agent: probe/1.0' http://localhost:8000/c/
```

```json
{"ua": "probe/1.0"}
```

## Call The Marker In The Annotation

`UserAgent()` is called rather than named, because a marker can take an
argument. Whatever you pass arrives as the factory's first parameter, so one
marker can serve many handlers:

```python
HeaderValue = create_param_decorator(
    lambda name, context: context.switch_to_http()
    .get_request()
    .headers.get(str(name), "")
)


@Controller("/h")
class HController:
    @Get("/")
    def read(self, trace: Annotated[str, HeaderValue("x-trace-id")]) -> dict[str, str]:
        return {"trace": trace}
```

A marker used with no argument still receives `None`, which is why the first
example ignores its `data` parameter.

## Keep It A Read

The function runs on the way in, for every request that reaches the handler. It
should read something and return it.

Doing work there — a database call, anything that can fail — puts that work
outside the stages built to hold it, where an exception filter is not expecting
it. If you need to *decide* something, that is a guard. If you need to
*transform* a value that is already bound, that is a pipe.
[Choose A Pipeline Hook](choose-a-pipeline-hook.md) is the longer form of that
argument.

The factory may be async, and is awaited when it is.
