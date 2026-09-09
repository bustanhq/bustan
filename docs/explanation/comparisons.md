# Comparisons

`Bustan` is easiest to evaluate when you frame it as an architecture layer rather than as a "more convenient Starlette" or a direct FastAPI clone.

## `Bustan` Vs Starlette

- Choose Starlette when you want a minimal ASGI toolkit and you prefer to assemble architecture yourself.
- Choose `Bustan` when the main problem is keeping a growing app organized with explicit modules, DI-managed services, lifecycle stages, and a predictable request pipeline.

Starlette remains the default execution engine under the hood. Bustan adds structure, not a competing transport stack.

## `Bustan` Vs FastAPI

- Choose FastAPI when schema-first API ergonomics, automatic docs, and request/response model convenience are the primary goals.
- Choose `Bustan` when the main problem is application composition, module boundaries, provider visibility, and scaling service wiring over time.

FastAPI optimizes around endpoint ergonomics. Bustan optimizes around architecture and runtime composition.

## `Bustan` Vs Litestar

Litestar is the nearest neighbour, and the comparison a reader who has already set FastAPI aside will make. The two agree on the decision that separates both of them from the Flask lineage: a route decorator binds nothing. `@get` in Litestar and `@Get` here attach to the function, a controller class groups the handlers, and the application is handed the result at construction rather than being the object every handler file has to import. They part on what the composition unit is, how a dependency reaches a handler, and what sits underneath.

- Choose Litestar when the application is a web application first: websockets, server-sent events, templates and sessions matter, the data layer is the problem, or the team wants one dependency that does all of it.
- Choose `Bustan` when the problem is composition: which part of the application may see which provider, dependencies checked before the first request, the same modules serving HTTP today and a queue tomorrow, and a request pipeline whose components are injected like everything else.

**The composition unit.** Litestar composes by path. A `Router` carries a prefix, and the four layers - application, router, controller, handler - accept the same parameters: `dependencies`, `guards`, `middleware`, `exception_handlers`, `before_request`, `after_request`, `opt`. A value set on a layer applies to everything beneath it, so a dependency declared on the application is visible to every handler the application serves. Bustan composes by visibility. A `Module` carries no prefix at all; it names the controllers and providers it owns, the modules it imports and the providers it exports, and a provider one module does not export cannot be injected from another. That is the difference between a URL tree and a dependency graph, and it is why the module graph can be validated, drawn and diffed where a Litestar application has a route table to list.

**Injection.** A Litestar dependency is a callable registered under a name, `dependencies={"posts": Provide(provide_posts)}`, and it reaches a handler through the parameter that shares the name. The name is the contract: rename the parameter and it becomes a query parameter, answered with a 400 by the first request that reaches it. The callable runs once per request unless `use_cache=True`, which keeps its result for the life of the application; those are the two lifetimes a dependency can have. A Litestar controller has no constructor of its own - the framework instantiates it once with the router that owns it - and a guard is a function of the connection and the handler that nothing is injected into.

Bustan injects through the constructor, and the annotation is the contract:

```python
@Controller("/posts")
class PostsController:
    def __init__(self, posts: PostService) -> None:
        self.posts = posts

    @Get("/")
    def list_posts(self) -> list[dict[str, object]]:
        return self.posts.list_posts()
```

`PostService` is resolved by type while the application is built, so a provider that is missing, unexported or scoped wrongly refuses to start rather than failing a request. Providers have four lifetimes - singleton, request, durable and transient - and lifecycle hooks the framework runs along the module graph; a controller can take a lifetime too, and one built per request can hold the requesting actor. A guard, a pipe, an interceptor or a filter is a class the container builds, so it can be given a provider the same way a controller is. The handler stays a method on a plain class: `@Get` returns the function it was given, so a test can construct the controller with a fake and call the method. Litestar's `@get` returns a handler object, and the function is its `fn` attribute.

**What sits underneath.** Litestar is the ASGI application. It owns its router, its request and response types and its serialization, and it does not depend on Starlette. Bustan compiles routes into a transport-neutral plan and hands it to an adapter; the Starlette adapter is the default and a raw ASGI adapter ships beside it. The same declarations serve on either, the kernel imports no web server, and `create_app_context` runs the same modules and providers with no HTTP served at all, for a worker or a command. Owning the stack is where Litestar's speed comes from; sitting above one is what lets Bustan swap it.

**Where Litestar is ahead.** It is the mature one of the two, stable at 2.x since 2023 and maintained by an organisation, where Bustan is a release candidate. It serves websockets, server-sent events, channels, templates, static files and sessions; Bustan serves HTTP and streams an iterator, and neither of its adapters upgrades a websocket. Its data layer is broader: msgspec, Pydantic, attrs and dataclasses, with DTOs that shape what comes in and what goes out, where Bustan binds Pydantic models and dataclasses and validates through Pydantic. Litestar also ships events, stores and a SQLAlchemy integration that Bustan has no equivalent for.

Both make the same first choice. Litestar then puts its effort into the transport; Bustan puts its into the graph above it.

## `Bustan` Vs NestJS

- Choose NestJS when you want the same architectural ideas in the TypeScript ecosystem.
- Choose `Bustan` when you want that module-and-provider style in Python while keeping direct access to an ASGI platform.

Bustan borrows the module, provider, lifecycle, and pipeline ideas, but it stays Python-native in typing, runtime, and framework integration.

One borrowed name means something narrower here. `INQUIRER` yields the requesting **class**, not the requesting instance as it does in NestJS. Bustan injects through the constructor and nowhere else, so a provider is built while its consumer is still being built: at the moment `INQUIRER` is answered, the consumer's `__init__` has not run and there is no instance to hand over. NestJS can answer with an object because it creates an empty one from the prototype before resolving arguments and fills it in afterwards, which is a half-built object with none of its fields set. Bustan hands over the class instead, which is the part that is actually known and the part callers use, typically to name the consumer in a log line:

```python
@Injectable(scope=Scope.TRANSIENT)
class Journal:
    def __init__(self, inquirer: Annotated[object, Inject(INQUIRER)]) -> None:
        # The class that asked for this journal, not an instance of it.
        self.owner = inquirer.__name__
```

This is a deliberate difference rather than a missing feature. `INQUIRER` can only be injected into a transient provider, because any cached lifetime would let one consumer's answer be handed to the next.

## What Bustan Is Optimizing For

- explicit module boundaries through `imports`, `providers`, `controllers`, and `exports`
- constructor injection for controllers and providers
- request-local state without global mutable context
- predictable request-time execution through guards, pipes, interceptors, and filters
- runtime inspection through route snapshots and discovery helpers
- direct platform access instead of hiding Starlette behind an opaque abstraction