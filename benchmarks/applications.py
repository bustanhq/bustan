"""The application shapes the benchmarks measure, one module per shape.

Each application is the smallest one that exercises the thing its benchmark is named
for, and the simple and pipelined routes are deliberately identical apart from the
pipeline components, so the difference between those two measurements is the pipeline
and nothing else.
"""

from __future__ import annotations

from typing import Annotated

from bustan import (
    CallHandler,
    Controller,
    ExecutionContext,
    Get,
    Guard,
    HttpRequest,
    Injectable,
    Interceptor,
    Module,
    Param,
    Pipe,
    Scope,
    UseGuards,
    UseInterceptors,
    UsePipes,
)

# Every route below answers with this payload built around one integer, so the cost of
# producing and serializing a response is the same in each of them.
ITEM_PATH = "/items/7"


def _describe(item_id: int) -> dict[str, object]:
    return {"item_id": item_id, "name": f"item-{item_id}", "in_stock": True}


@Injectable()
class CatalogService:
    """A default-scoped provider a controller injects, so injection is on the path."""

    def read(self, item_id: int) -> dict[str, object]:
        return _describe(item_id)


# --- A route with nothing on it but injection and binding -------------------------


@Controller("/items")
class SimpleController:
    def __init__(self, catalog: CatalogService) -> None:
        self.catalog = catalog

    @Get("/{item_id}")
    def read_item(self, item_id: Annotated[int, Param]) -> dict[str, object]:
        return self.catalog.read(item_id)


@Module(controllers=[SimpleController], providers=[CatalogService])
class SimpleModule:
    pass


# --- The same route, with a guard, a pipe and an interceptor around it -------------


@Injectable()
class AlwaysAllowGuard(Guard):
    async def can_activate(self, context: ExecutionContext) -> bool:
        return context is not None


class ClampPipe(Pipe):
    def transform(self, value: object, context: ExecutionContext) -> object:
        return min(int(value), 1_000_000) if isinstance(value, int | str) else value


@Injectable()
class EnvelopeInterceptor(Interceptor):
    async def intercept(self, context: ExecutionContext, next: CallHandler) -> object:
        return {"data": await next.handle()}


@UseGuards(AlwaysAllowGuard)
@UseInterceptors(EnvelopeInterceptor)
@UsePipes(ClampPipe)
@Controller("/items")
class PipelineController:
    def __init__(self, catalog: CatalogService) -> None:
        self.catalog = catalog

    @Get("/{item_id}")
    def read_item(self, item_id: Annotated[int, Param]) -> dict[str, object]:
        return self.catalog.read(item_id)


@Module(
    controllers=[PipelineController],
    providers=[CatalogService, AlwaysAllowGuard, EnvelopeInterceptor],
)
class PipelineModule:
    pass


# --- A chain that is rebuilt for every request -------------------------------------


@Injectable(scope=Scope.REQUEST)
class RequestIdentity:
    def __init__(self, request: HttpRequest) -> None:
        self.path = request.url.path


@Injectable(scope=Scope.REQUEST)
class RequestAudit:
    def __init__(self, identity: RequestIdentity, catalog: CatalogService) -> None:
        self.identity = identity
        self.catalog = catalog


@Injectable(scope=Scope.REQUEST)
class RequestReporter:
    def __init__(self, audit: RequestAudit) -> None:
        self.audit = audit

    def read(self, item_id: int) -> dict[str, object]:
        return {**self.audit.catalog.read(item_id), "path": self.audit.identity.path}


@Controller("/items", scope=Scope.REQUEST)
class RequestScopedController:
    def __init__(self, reporter: RequestReporter) -> None:
        self.reporter = reporter

    @Get("/{item_id}")
    def read_item(self, item_id: Annotated[int, Param]) -> dict[str, object]:
        return self.reporter.read(item_id)


@Module(
    controllers=[RequestScopedController],
    providers=[CatalogService, RequestIdentity, RequestAudit, RequestReporter],
)
class RequestScopedModule:
    pass


# --- A resolution chain with no HTTP anywhere near it ------------------------------


@Injectable()
class SettingsProvider:
    value = "settings"


@Injectable()
class StorageProvider:
    def __init__(self, settings: SettingsProvider) -> None:
        self.settings = settings


@Injectable(scope=Scope.TRANSIENT)
class ReportBuilder:
    """Transient, so resolving it walks the chain again instead of reading a cache."""

    def __init__(self, storage: StorageProvider, catalog: CatalogService) -> None:
        self.storage = storage
        self.catalog = catalog


@Module(providers=[CatalogService, SettingsProvider, StorageProvider, ReportBuilder])
class ResolutionModule:
    pass
