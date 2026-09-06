# ruff: noqa
# Evidence script for finding EX-01 (workflow id F-85) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
# F-85: exceptions raised while DI constructs the controller / request-scoped
# providers (execution.py:122) happen before ExecutionContext (128) and
# observability.start_request (145), so the except branch (185-194) renders a
# bare 500 without consulting route filters, APP_FILTER, problem-details
# mapping or metrics. Control: same exception inside the handler -> 400 + metrics.
from typing import Any, cast

from starlette.testclient import TestClient

from bustan import Controller, ExceptionFilter, ExecutionContext, Get, Injectable, Module, Scope, UseFilters, create_app
from bustan.kernel.errors import BadRequestException, GuardRejectedError
from bustan.kernel.ioc.tokens import APP_FILTER
from bustan.observability.observability import ObservabilityHooks


class RecordingMetrics:
    def __init__(self) -> None:
        self.records: list[dict[str, str]] = []

    def record_request(self, *, labels: dict[str, str]) -> None:
        self.records.append(labels)


class CatchAll(ExceptionFilter):
    exception_types = (Exception,)
    calls = 0

    async def catch(self, exc: Exception, context: ExecutionContext) -> object:
        CatchAll.calls += 1
        return {"detail": "filtered", "type": type(exc).__name__}


def build(exc_factory):
    @Injectable(scope=Scope.REQUEST)
    class CurrentUser:
        def __init__(self) -> None:
            raise exc_factory()

    @Controller("/me", scope=Scope.REQUEST)
    class MeController:
        def __init__(self, user: CurrentUser) -> None:
            self.user = user

        @UseFilters(CatchAll())
        @Get("/")
        def read(self) -> dict[str, str]:
            return {"ok": "yes"}

    @Module(controllers=[MeController], providers=[CurrentUser, {"provide": APP_FILTER, "use_value": CatchAll()}])
    class AppModule:
        pass

    return create_app(AppModule)


outcomes = {}
for name, factory in (
    ("BadRequestException", lambda: BadRequestException("missing header", field="x-user", source="header")),
    ("GuardRejectedError", lambda: GuardRejectedError("no token")),
):
    metrics = RecordingMetrics()
    CatchAll.calls = 0
    with ObservabilityHooks.scoped_override(ObservabilityHooks(metrics=cast(Any, metrics))):
        with TestClient(build(factory), raise_server_exceptions=False) as client:
            response = client.get("/me")
    outcomes[name] = (response.status_code, CatchAll.calls, len(metrics.records))
    print(f"{name} in request-scoped ctor -> status={response.status_code} body={response.text[:100]!r} "
          f"filter_calls={CatchAll.calls} metrics_records={len(metrics.records)} "
          f"content-type={response.headers.get('content-type')}")


# Control: same exception in the handler body.
@Controller("/ctl")
class HandlerRaises:
    @Get("/")
    def read(self) -> None:
        raise BadRequestException("missing header", field="x-user", source="header")


@Module(controllers=[HandlerRaises])
class ControlModule:
    pass


metrics = RecordingMetrics()
with ObservabilityHooks.scoped_override(ObservabilityHooks(metrics=cast(Any, metrics))):
    with TestClient(create_app(ControlModule), raise_server_exceptions=False) as client:
        ctrl = client.get("/ctl")
print(f"control: BadRequestException in handler -> status={ctrl.status_code} body={ctrl.text[:120]!r} "
      f"metrics_records={len(metrics.records)}")

confirmed = (
    outcomes["BadRequestException"] == (500, 0, 0)
    and outcomes["GuardRejectedError"] == (500, 0, 0)
    and ctrl.status_code == 400
    and len(metrics.records) == 1
)
print("F-85 RESULT:", "CONFIRMED" if confirmed else "REFUTED", outcomes)
