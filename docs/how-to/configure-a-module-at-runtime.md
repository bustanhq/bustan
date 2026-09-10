# Configure A Module At Runtime

A static `@Module` declares the same providers every time. When a module needs a
value that is only known once the process starts — a prefix, a connection
string, a timeout — give it a classmethod that returns a `DynamicModule`.

```python
from bustan import (
    DynamicModule,
    FactoryProvider,
    InjectionToken,
    Module,
    ValueProvider,
)

from .cache_service import CacheService

CACHE_PREFIX = InjectionToken[str]("CACHE_PREFIX")


@Module(exports=[CacheService])
class CacheModule:
    @classmethod
    def register(cls, prefix: str) -> DynamicModule:
        return DynamicModule(
            module=cls,
            providers=(
                ValueProvider(provide=CACHE_PREFIX, use_value=prefix),
                FactoryProvider(
                    provide=CacheService,
                    use_factory=CacheService,
                    inject=(CACHE_PREFIX,),
                ),
            ),
            exports=(CacheService,),
        )
```

Import the result of calling it, not the class:

```python
@Module(imports=[CacheModule.register("app:")], controllers=[AppController])
class AppModule:
    pass
```

## The Provider Forms

`providers` takes the provider types, one per way of binding a token:

| Type | Binds the token to |
| --- | --- |
| `ValueProvider(provide=, use_value=)` | a value you already have |
| `FactoryProvider(provide=, use_factory=, inject=)` | the result of calling a factory with the resolved tokens |
| `ClassProvider(provide=, use_class=)` | an instance the container builds |
| `ExistingProvider(provide=, use_existing=)` | whatever another token is bound to |

A dictionary is not a provider. `{"provide": X, "use_value": Y}` was accepted
before 2.0 and is now refused at compile time with `InvalidProviderError`, which
names the replacement:

```text
Invalid provider in CacheModule[0]: a dict is no longer a provider.
Replace {"provide": X, "use_value": Y} with ValueProvider(provide=X, use_value=Y)
```

`FactoryProvider` and `ClassProvider` also take `scope`; see
[Declare Request Scope](../explanation/request-scope.md#declare-request-scope)
for what that changes and what it costs.

## Build The Token Once

An `InjectionToken` is its own identity. Two tokens are the same token only when
they are the same object, so `InjectionToken("CACHE_PREFIX")` written in two
files is two unrelated tokens and one will never resolve the other, however
identical they look. Declare it at module level and import it.

The name is what the token is called in an error message; the container never
matches two tokens by comparing names.

## When Not To Reach For This

If the value is available where you write the code, a plain `@Module` carrying a
`ValueProvider` is simpler and does the same thing. Dynamic modules are for
values that arrive at startup, not for values that merely arrive from elsewhere
in your source.
