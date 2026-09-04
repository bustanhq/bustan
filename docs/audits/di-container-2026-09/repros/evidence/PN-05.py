# ruff: noqa
# Evidence script for finding PN-05 (workflow id F-33) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-33: undecorated class registered as provider is container-resolvable but the
pipeline factory builds it with comp_type() (no-arg) and 500s."""
from starlette.testclient import TestClient
from bustan import Module, Controller, Get, UseGuards, Guard, Injectable, create_app, create_app_context
from bustan.core.errors import InvalidPipelineError

@Injectable()
class Policy:
    allowed = True

class PlainGuard(Guard):  # registered provider, NO @Injectable
    def __init__(self, policy: Policy) -> None:
        self.policy = policy
    def can_activate(self, context):
        return self.policy.allowed

@Module(providers=[Policy, PlainGuard])
class M0: pass
inst = create_app_context(M0).get(PlainGuard)
print("container.get(PlainGuard) ->", type(inst).__name__, "policy injected:", isinstance(inst.policy, Policy))

@Controller("/x")
class C:
    @Get("/")
    @UseGuards(PlainGuard)
    def h(self):
        return {"ok": True}

@Module(controllers=[C], providers=[Policy, PlainGuard])
class M: pass
app = create_app(M)
status = None
with TestClient(app, raise_server_exceptions=False) as client:
    for i in range(2):
        r = client.get("/x/")
        status = r.status_code
        print(f"GET /x/ attempt {i+1} ->", r.status_code, r.text[:160])

# capture the exception type deterministically via the factory (the HTTP layer swallows it into a 500)
from bustan.platform.http.controller_factory import ControllerFactory
from bustan.pipeline.metadata import PipelineMetadata
factory = ControllerFactory(app.container)
req = __import__("starlette.requests", fromlist=["Request"]).Request({"type": "http", "method": "GET", "path": "/", "headers": []})
try:
    factory.resolve_components((PlainGuard,), Guard, module=M, request=req, kind="guard")
    print("factory.resolve_components: no exception")
except InvalidPipelineError as exc:
    print("factory.resolve_components raised:", type(exc).__name__, "|", exc)
    print("   chained from:", type(exc.__cause__).__name__, "|", exc.__cause__)

print("RESULT:", "CONFIRMED - registered undecorated guard resolves via container but 500s in pipeline"
      if status == 500 else f"REFUTED - status {status}")
