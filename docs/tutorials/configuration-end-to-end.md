# Settings That Live Outside The Code

Your shortener works, and it has a `6` in it:

```python
code = "".join(secrets.choice(ALPHABET) for _ in range(6))
```

Six characters from a 36-character alphabet is about two billion codes, which is plenty. Until you
run the same code on a staging box where you would rather have short ugly codes, or a customer asks
for vanity links, and now you are editing source to change a number.

That number belongs outside the code. So does the page size, and so will the database path in the
next tutorial, and so will an API token in the one after. This tutorial moves all of it out, and
makes the application refuse to start when a setting is missing or wrong.

## The Obvious Way, And Why It Is Not Enough

You could reach for the environment directly:

```python
self._code_length = int(os.environ.get("CODE_LENGTH", 6))
```

That works and it has three problems you will meet in order. Nothing tells you which variables the
application reads, so nobody can deploy it without reading the source. Nothing checks them, so
`CODE_LENGTH=banana` is a crash on the first request rather than a refusal at startup. And every
class that needs a setting grows its own parsing.

The framework has a module for this.

## Loading Settings

Import the configuration module in `src/my_app/app_module.py`:

```python
from bustan import ConfigModule, Module

from .links.links_module import LinksModule


@Module(imports=[ConfigModule.for_root(), LinksModule])
class AppModule:
    pass
```

`for_root()` reads the process environment and makes a `ConfigService` available to inject. Now ask
for one in `LinksService`:

```python
from bustan import ConfigService, Injectable


@Injectable()
class LinksService:
    def __init__(self, config: ConfigService) -> None:
        self._code_length = int(config.get("CODE_LENGTH", 6))
        self._links: dict[str, str] = {}
```

Then spend it where the `6` used to be:

```python
    def create_link(self, url: str) -> str:
        code = "".join(secrets.choice(ALPHABET) for _ in range(self._code_length))
```

`get` takes a default, so this still works with nothing set. Try it:

```bash
CODE_LENGTH=3 uv run dev
```

```bash
curl -X POST http://127.0.0.1:3000/links -H 'content-type: application/json' \
  -d '{"url": "https://example.com"}'
```

```json
{"code":"q4z"}
```

Three characters. You changed behaviour without touching a file.

## Keeping Settings Somewhere You Can Read Them

Typing variables in front of every command gets old, and it does not survive a reboot. Put them in a
file instead. Create `.env` next to `pyproject.toml`:

```bash
CODE_LENGTH=6
PAGE_SIZE=20
```

Point the config module at it:

```python
ConfigModule.for_root(env_file=".env")
```

Add `.env` to your `.gitignore` now, before you put anything secret in it. In production you will not
ship this file at all; the same names arrive as real environment variables, and an environment
variable beats the file when both are set. That is the whole deployment story for configuration, and
you will prove it at the end of this page.

## One Thing Worth Knowing About `for_root`

`ConfigModule.for_root()` is global. Every module can inject `ConfigService` without importing
anything, which is why `LinksService` worked a moment ago even though `LinksModule` imports nothing
new.

That is deliberate, and it is the exception rather than the pattern. The last tutorial's `exports`
list existed to stop modules reaching into each other, and here is a module that reaches everywhere.
It earns it because configuration genuinely is needed everywhere. Almost nothing else is. If you find
yourself making a module global to fix an import error, the import error was telling you something,
and [Layering](../explanation/layering.md) is about what.

## Refusing To Start On A Bad Setting

Right now `CODE_LENGTH=banana` gets you a `ValueError` from `int()` on the first request that needs a
code. Nobody is watching at that moment. Better to fail while starting, when somebody is.

Describe the settings as a model. Create `src/my_app/settings.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, Field


class Settings(BaseModel):
    model_config = {"extra": "ignore"}

    CODE_LENGTH: int = Field(default=6, ge=3, le=32)
    PAGE_SIZE: int = Field(default=20, ge=1, le=100)
```

`extra: ignore` is not optional. Your environment has `PATH`, `HOME` and a hundred others, and
without that line every one of them is an unexpected field.

Hand the model to the config module:

```python
ConfigModule.for_root(env_file=".env", validation_schema=Settings)
```

Now break it on purpose. In `.env`:

```bash
CODE_LENGTH=banana
```

```bash
uv run dev
```

```text
pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
CODE_LENGTH
  Input should be a valid integer, unable to parse string as an integer
  [type=int_parsing, input_value='banana', input_type=str]
```

No server starts. The message names the setting and what was wrong with it, and it arrives before a
single request. Try `CODE_LENGTH=1` too, which is a valid integer and still refused, because the
model says three is the minimum.

Causing this once, deliberately, is worth a minute. The alternative is meeting it for the first time
during a deployment, when it looks like a mystery rather than a message.

Put a real value back.

## Seeing What The Application Actually Resolved

There is a command for the question "is it even reading my `.env`":

```bash
uv run bustan config my_app.app_module:AppModule
```

It compiles the application and prints what the configuration module resolved, after the file and the
environment have been merged. `for_root` reads the whole process environment, so that is a row for
every variable your shell exports as well as the two you set, and the two you set are easier found
with a filter:

```bash
uv run bustan config my_app.app_module:AppModule | grep -E 'CODE_LENGTH|PAGE_SIZE'
```

```text
CODE_LENGTH   6
PAGE_SIZE     20
```

The key column is padded to the longest name in the whole table, so where the value column starts
depends on your environment rather than on this page. Run this before writing code that depends on
a value, not after.

One thing that surprises people: a key whose name reads like a credential is printed as `[redacted]`
rather than its value. You will see that in the next tutorial when you add a token. It is the command
working, not failing.

## Proving The Environment Wins

```bash
CODE_LENGTH=10 uv run bustan config my_app.app_module:AppModule | grep CODE_LENGTH
```

```text
CODE_LENGTH   10
```

Ten, not the six in the file. That single behaviour is what lets one built artifact run in three
environments: the image is identical, the environment differs, nothing is rebuilt. Everything in
[Deploy An Application](../how-to/deploy.md) assumes it.

## Where This Leaves You

Settings are outside the code, validated once, and visible from a command line. The service reads
them without knowing where they came from.

The links themselves are still in a dictionary that empties when you restart, which is the next
thing to fix: [Links That Survive A Restart](a-datastore-and-a-readiness-probe.md).
