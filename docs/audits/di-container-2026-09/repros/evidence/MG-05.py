# ruff: noqa
# Evidence script for finding MG-05 (workflow id F-28) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-28: DynamicModule identity is id()-based."""
from bustan import Injectable, Module, create_app
from bustan.addons.module_ref import ModuleRef
from bustan.kernel.module.dynamic import DynamicModule
from bustan.kernel.module.graph import build_module_graph
from bustan.kernel.ioc.container import build_container
from bustan.kernel.ioc.tokens import InjectionToken
from bustan.kernel.errors import InvalidModuleError

TOKEN = InjectionToken("OPTS")


@Injectable
class Counter:
    pass


@Module(providers=[Counter], exports=[Counter])
class ConfigModule:
    pass


def for_root(value):
    return DynamicModule(ConfigModule, providers=({"provide": TOKEN, "use_value": value},), exports=(TOKEN,))


dm = for_root(1)
dm_equal = for_root(1)
print("dm == dm_equal:", dm == dm_equal, "; dm is dm_equal:", dm is dm_equal)


@Module(imports=[dm])
class M1:
    pass


@Module(imports=[dm_equal])
class M3:
    pass


@Module(imports=[M1, M3])
class AppEqual:
    pass


g = build_module_graph(AppEqual)
cfg_nodes = [n.key for n in g.nodes if n.module is ConfigModule]
print("equal values imported by M1 and M3 -> ConfigModule nodes:", cfg_nodes)
c = build_container(g)
same = c.resolve(Counter, module=M1) is c.resolve(Counter, module=M3)
print("resolve(Counter, M1) is resolve(Counter, M3):", same)
singletons = [k for k in c.scope_manager.singletons if k[1] is Counter]
print("Counter singleton cache entries:", singletons)
part_a = len(cfg_nodes) == 2 and not same

print("---- duplicate entries: [Mod, Mod] vs [dm, dm] vs [dm, dm_equal] ----")
res = {}
for label, imports in (("[ConfigModule, ConfigModule]", [ConfigModule, ConfigModule]), ("[dm, dm]", [dm, dm]), ("[dm, dm_equal]", [dm, dm_equal])):
    try:
        Dup = Module(imports=imports)(type("Dup", (), {}))
        build_module_graph(Dup)
        res[label] = "accepted"
    except InvalidModuleError as exc:
        res[label] = f"InvalidModuleError: {exc}"
    print(label, "->", res[label])
part_b = res["[ConfigModule, ConfigModule]"].startswith("InvalidModuleError") and res["[dm, dm]"].startswith("InvalidModuleError") and res["[dm, dm_equal]"] == "accepted"

print("---- instance ids shift with traversal order ----")
dmA = for_root("A")
dmB = for_root("B")


@Module(imports=[dmA])
class MA:
    pass


@Module(imports=[dmB])
class MB:
    pass


@Module(imports=[MA, MB])
class Order1:
    pass


@Module(imports=[MB, MA])
class Order2:
    pass


k1 = list(build_module_graph(Order1).get_node(MA).imported_exports.keys())[0]
k2 = list(build_module_graph(Order2).get_node(MA).imported_exports.keys())[0]
print("key of dmA when MA visited first:", k1)
print("key of dmA when MB visited first:", k2)
part_c = k1 != k2

print("---- ModuleRef.for_module(ConfigModule) with two instances ----")
d1 = for_root("one")
d2 = for_root("two")


@Module(imports=[d1])
class N1:
    pass


@Module(imports=[d2])
class N2:
    pass


@Module(imports=[N1, N2])
class App:
    pass


app = create_app(App)
ref = ModuleRef._from_application(app)
scoped = ref.for_module(ConfigModule)
val = scoped.get(TOKEN)
print("for_module(ConfigModule) ->", scoped.module_key, "; get(TOKEN) =", repr(val))
print("ConfigModule nodes present:", [n.key for n in app.module_graph.nodes if n.module is ConfigModule])
part_d = val == "one"

if part_a and part_b and part_c and part_d:
    print("RESULT: CONFIRMED - equal DynamicModules become separate instances/singletons; [dm, dm_equal] accepted; instance ids shift; ModuleRef silently picks first")
else:
    print("RESULT: NOT CONFIRMED", part_a, part_b, part_c, part_d)
