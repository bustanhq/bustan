# ruff: noqa
# Evidence script for finding RI-09 (workflow id F-34) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-34: _detect_owner_scope scans registry.bindings in insertion order, ignoring the
requesting module, so instantiate_class() scope inference depends on registration order."""
from __future__ import annotations
from starlette.requests import Request
from bustan import Injectable, Module, create_app, create_app_context, ModuleRef
from bustan.kernel.errors import ProviderResolutionError

@Injectable(scope="request")
class RequestState:
    def __init__(self, request: Request) -> None:
        self.request = request

class Reporter:  # bound via use_class in two modules with different scopes
    def __init__(self, state: RequestState) -> None:
        self.state = state

@Module(providers=[RequestState, {"provide": "REPORTER_REQ", "use_class": Reporter, "scope": "request"}],
        exports=["REPORTER_REQ", RequestState])
class ReqFirstModule: ...

@Module(providers=[RequestState, {"provide": "REPORTER_SINGLETON", "use_class": Reporter}],
        exports=["REPORTER_SINGLETON"])
class SingletonModule: ...

def make_request():
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})

outcomes = {}
for order in ([ReqFirstModule, SingletonModule], [SingletonModule, ReqFirstModule]):
    @Module(imports=order, providers=[RequestState])
    class Root: ...
    app = create_app(Root)
    scan = app.container.resolver._detect_owner_scope(Reporter)
    names = [m.__name__ for m in order]
    print("imports", names, "-> _detect_owner_scope(Reporter) =", scan)
    try:
        inst = app.container.instantiate_class(Reporter, module=Root, request=make_request())
        outcomes[tuple(names)] = "OK"
        print("   instantiate_class(Reporter, module=Root, request=...) OK; state.request set:",
              inst.state.request is not None)
    except ProviderResolutionError as exc:
        outcomes[tuple(names)] = "FAIL"
        print("   instantiate_class(Reporter, module=Root, request=...) FAILED:", str(exc)[:140])

# Part 2: same class bare + dict with scope in a single module: which wins depends on list order
@Injectable()
class NeedsReq:
    def __init__(self, request: Request) -> None:
        self.request = request

@Module(providers=[{"provide": "req-scoped", "use_class": NeedsReq, "scope": "request"}, NeedsReq])
class DictFirst: pass
@Module(providers=[NeedsReq, {"provide": "req-scoped", "use_class": NeedsReq, "scope": "request"}])
class BareFirst: pass
for mod in (DictFirst, BareFirst):
    ctx = create_app_context(mod)
    print(mod.__name__, "-> _detect_owner_scope(NeedsReq) =", ctx.container.resolver._detect_owner_scope(NeedsReq))
    try:
        ctx.container.instantiate_class(NeedsReq, module=mod, request=make_request())
        print("   instantiate_class(NeedsReq, request=...) OK (Request injected)")
    except ProviderResolutionError as exc:
        print("   instantiate_class(NeedsReq, request=...) FAILED:", str(exc)[:120])

# Part 3: does the ORDINARY resolve path (binding_scope passed) also depend on order?  (expect no)
@Module(providers=[RequestState, {"provide": "REPORTER_SINGLETON", "use_class": Reporter},
                   {"provide": "REPORTER_REQ", "use_class": Reporter, "scope": "request"}])
class Single: ...
ctx = create_app_context(Single)
try:
    ctx.container.resolve("REPORTER_SINGLETON", module=Single)
    print("resolve('REPORTER_SINGLETON') unexpectedly OK")
except ProviderResolutionError as exc:
    print("resolve('REPORTER_SINGLETON') correctly blocked (binding_scope given):", str(exc)[:90])
print("resolve('REPORTER_REQ', request=...) ->",
      type(ctx.container.resolve("REPORTER_REQ", module=Single, request=make_request())).__name__)

vals = set(outcomes.values())
print("RESULT:", "CONFIRMED - instantiate_class outcome flips with import order:" + str(outcomes)
      if len(vals) == 2 else "REFUTED - outcome independent of order: " + str(outcomes))
