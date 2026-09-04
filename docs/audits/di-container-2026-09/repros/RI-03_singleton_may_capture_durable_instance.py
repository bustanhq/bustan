# ruff: noqa
"""The scope guard rejects only REQUEST dependencies, never DURABLE ones.

A singleton provider is allowed to depend on a durable-scoped provider. The
singleton is built once, captures whichever tenant partition happened to be
active first, and serves it to every later tenant for the life of the process.
"""

from __future__ import annotations

from starlette.requests import Request

from bustan import Injectable, Module, Scope, create_app_context
from bustan.core.errors import ProviderResolutionError


@Injectable(scope=Scope.DURABLE)
class TenantCache:
    @classmethod
    def get_durable_context_key(cls, request: Request | None):
        if request is None:
            return "no-request"
        return request.headers.get("x-tenant", "unknown")

    def __init__(self) -> None:
        self.tenant = "captured-at-construction"


@Injectable()  # defaults to SINGLETON
class ReportService:
    def __init__(self, cache: TenantCache) -> None:
        self.cache = cache


@Module(providers=[TenantCache, ReportService])
class AppModule:
    pass


def main() -> None:
    try:
        context = create_app_context(AppModule)
        service = context.get(ReportService)
    except ProviderResolutionError as exc:
        print(f"REJECTED: {exc}")
        print("RESULT: RI-03 FIXED - a singleton owner may no longer reach durable scope")
        return

    print(f"singleton ReportService built, holding durable {type(service.cache).__name__}")
    print("RESULT: RI-03 REPRODUCED - a singleton captured a tenant-keyed durable instance")


main()
