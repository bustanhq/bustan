# ruff: noqa
# Evidence script for finding RF-11 (workflow id F-88) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
# F-88: constructor introspection edge cases (resolver.py:542-592).
#  (a) eager constructor.__globals__ default -> raw AttributeError for C __init__
#  (b) only NameError/TypeError caught -> raw SyntaxError for "List["
#  (c) first parameter skipped by literal name "self" -> `this` is a dependency
#  (d) special tokens resolved before OptionalDep -> Inject(REQUEST)+OptionalDep in a singleton raises
from __future__ import annotations

from typing import Annotated

from bustan import Inject, Injectable, Module, OptionalDep
from bustan.app.bootstrap import create_app_context
from bustan.kernel.errors import ProviderResolutionError
from bustan.kernel.ioc.tokens import REQUEST


def run(label, module_cls, token):
    ctx = create_app_context(module_cls)
    try:
        value = ctx.get(token)
        print(f"{label}: OK -> {type(value).__name__}")
        return "ok"
    except ProviderResolutionError as exc:
        print(f"{label}: ProviderResolutionError: {str(exc)[:150]}")
        return "ProviderResolutionError"
    except Exception as exc:  # noqa: BLE001
        print(f"{label}: RAW {type(exc).__name__}: {str(exc)[:150]}")
        return "RAW " + type(exc).__name__


# (a) inherited C slot-wrapper __init__
@Injectable()
class HeaderMap(dict):
    pass


@Injectable()
class MyError(Exception):
    pass


@Module(providers=[HeaderMap, MyError])
class ModA:
    pass


res_a1 = run("(a) @Injectable class HeaderMap(dict)", ModA, HeaderMap)
res_a2 = run("(a) @Injectable class MyError(Exception)", ModA, MyError)


# (b) SyntaxError from a malformed string annotation
@Injectable()
class UsesBadSyntax:
    def __init__(self, dep: "List[") -> None:  # noqa: F722
        self.dep = dep


@Module(providers=[UsesBadSyntax])
class ModB:
    pass


res_b = run("(b) annotation 'List['", ModB, UsesBadSyntax)


# (c) first parameter not literally named self
@Injectable()
class Dep:
    pass


@Injectable()
class UsesThis:
    def __init__(this, dep: Dep) -> None:  # noqa: N805
        this.dep = dep


@Module(providers=[Dep, UsesThis])
class ModC:
    pass


res_c = run("(c) def __init__(this, dep: Dep)", ModC, UsesThis)


# (d) OptionalDep on a special token inside a singleton
@Injectable()
class OptionalRequestUser:
    def __init__(self, request: Annotated[object, Inject(REQUEST), OptionalDep()]) -> None:
        self.request = request


@Module(providers=[OptionalRequestUser])
class ModD:
    pass


res_d = run("(d) Annotated[object, Inject(REQUEST), OptionalDep()] in singleton", ModD, OptionalRequestUser)

# (d) control: OptionalDep on an ordinary unregistered token yields None.
MISSING = object()


@Injectable()
class OptionalPlain:
    def __init__(self, dep: Annotated[object, Inject(MISSING), OptionalDep()]) -> None:
        self.dep = dep


@Module(providers=[OptionalPlain])
class ModD2:
    pass


res_d2 = run("(d-control) OptionalDep on unregistered ordinary token", ModD2, OptionalPlain)

summary = dict(a_dict=res_a1, a_exc=res_a2, b=res_b, c=res_c, d=res_d, d_control=res_d2)
confirmed = (
    res_a1 == "RAW AttributeError"
    and res_a2 == "RAW AttributeError"
    and res_b == "RAW SyntaxError"
    and res_c == "ProviderResolutionError"
    and res_d == "ProviderResolutionError"
    and res_d2 == "ok"
)
print("F-88 RESULT:", "CONFIRMED" if confirmed else "PARTIAL/REFUTED", summary)
