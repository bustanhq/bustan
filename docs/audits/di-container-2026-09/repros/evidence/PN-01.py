# ruff: noqa
# Evidence script for finding PN-01 (workflow id F-09) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-09: provider metadata read with inheriting getattr -> undecorated subclass binds the parent."""
from __future__ import annotations

from starlette.testclient import TestClient

from bustan import Controller, Get, Guard, Injectable, Module, UseGuards, create_app, create_app_context
from bustan.common.constants import BUSTAN_PROVIDER_ATTR
from bustan.core.errors import InvalidModuleError, ProviderResolutionError
from bustan.core.ioc.registry import normalize_provider

results: list[tuple[str, bool, str]] = []


def record(name: str, defect_shown: bool, detail: str) -> None:
    results.append((name, defect_shown, detail))
    print(f"[{'DEFECT' if defect_shown else 'OK'}] {name}: {detail}")


constructed: list[str] = []


@Injectable()
class BaseRepo:
    def __init__(self) -> None:
        constructed.append(type(self).__name__)


class ChildRepo(BaseRepo):  # NOT decorated
    pass


# 1. normalize_provider reads the inherited dict
meta_is_shared = getattr(ChildRepo, BUSTAN_PROVIDER_ATTR) is getattr(BaseRepo, BUSTAN_PROVIDER_ATTR)
own_dict_has_meta = BUSTAN_PROVIDER_ATTR in ChildRepo.__dict__
binding = normalize_provider(ChildRepo, object())
record(
    "normalize_provider(ChildRepo)",
    binding.token is BaseRepo and binding.target is BaseRepo,
    f"token={binding.token.__name__} target={binding.target.__name__} "
    f"(meta shared with parent={meta_is_shared}, in ChildRepo.__dict__={own_dict_has_meta})",
)


# 2. providers=[ChildRepo]: Child cannot be resolved, Base gets constructed instead
@Module(providers=[ChildRepo])
class M1:
    pass


ctx = create_app_context(M1)
child_error = ""
try:
    ctx.get(ChildRepo)
except ProviderResolutionError as exc:
    child_error = str(exc)
base_instance_type = type(ctx.get(BaseRepo)).__name__
record(
    "providers=[ChildRepo]",
    bool(child_error) and base_instance_type == "BaseRepo" and "ChildRepo" not in constructed,
    f"get(ChildRepo) -> {child_error or 'resolved'!r}; get(BaseRepo) -> {base_instance_type}; constructed={constructed}",
)


# 3. providers=[BaseRepo, ChildRepo] -> duplicate error naming the parent
@Module(providers=[BaseRepo, ChildRepo])
class M2:
    pass


dup_error = ""
try:
    create_app_context(M2)
except InvalidModuleError as exc:
    dup_error = str(exc)
record("providers=[BaseRepo, ChildRepo]", "BaseRepo" in dup_error, f"-> {dup_error or 'no error'!r}")


# 4. Pipeline: undecorated subclass of an @Injectable guard in @UseGuards
@Injectable()
class BaseGuard(Guard):
    def can_activate(self, context) -> bool:
        return True


class StrictGuard(BaseGuard):  # NOT decorated, no-arg constructor
    pass


class PlainGuard(Guard):  # control: undecorated, no @Injectable anywhere in MRO
    def can_activate(self, context) -> bool:
        return True


@Controller("/x")
class XController:
    @Get("/strict")
    @UseGuards(StrictGuard)
    def strict(self):
        return {"ok": True}

    @Get("/plain")
    @UseGuards(PlainGuard)
    def plain(self):
        return {"ok": True}


for providers in ([], [StrictGuard], [BaseGuard]):
    @Module(controllers=[XController], providers=list(providers))
    class M3:
        pass

    app = create_app(M3)
    with TestClient(app, raise_server_exceptions=False) as client:
        strict = client.get("/x/strict")
        plain = client.get("/x/plain")
    record(
        f"@UseGuards(StrictGuard) with providers={[p.__name__ for p in providers]}",
        strict.status_code == 500,
        f"/x/strict -> {strict.status_code} {strict.text[:160]!r}; control /x/plain -> {plain.status_code}",
    )

print()
if all(shown for _, shown, _ in results):
    print("RESULT: CONFIRMED - undecorated subclass inherits @Injectable metadata; child bound/resolved under the parent identity and pipeline resolution breaks")
else:
    print("RESULT: NOT FULLY REPRODUCED -", [n for n, shown, _ in results if not shown])
