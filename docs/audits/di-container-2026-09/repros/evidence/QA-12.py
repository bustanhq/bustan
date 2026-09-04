# ruff: noqa
# Evidence script for finding QA-12 (workflow id F-78) from the 2026-09 DI container audit.
# Verbatim verification script; prints its own CONFIRMED/REFUTED lines. See ../../REPORT.md.
"""F-78: do the cited tests assert defective behaviour that the runtime actually exhibits?"""
import re, anyio
from pathlib import Path
repo = Path("/home/user/bustan")

def has(path, needle):
    text = (repo / path).read_text()
    return needle in text

checks = {}
# (1) test_registry pins scope drop on use_value and raw TypeError
checks["registry_test_pins_singleton_for_transient_use_value"] = has(
    "tests/unit/core/ioc/test_registry.py", '{"provide": "value", "use_value": 1, "scope": "transient"}') and has(
    "tests/unit/core/ioc/test_registry.py", "scope=ProviderScope.SINGLETON,\n    )\n    assert normalize_provider(\n        {\"provide\": \"alias\"")
checks["registry_test_expects_TypeError"] = has("tests/unit/core/ioc/test_registry.py", 'pytest.raises(TypeError, match="provide")')
from bustan.core.ioc.registry import normalize_provider
from bustan.common.types import ProviderScope
b = normalize_provider({"provide": "value", "use_value": 1, "scope": "transient"}, object)
checks["runtime_drops_explicit_scope_on_use_value"] = b.scope is ProviderScope.SINGLETON
try:
    normalize_provider({"use_value": 1}, object)
except Exception as exc:
    checks["runtime_raises_plain_TypeError"] = type(exc) is TypeError

# (2) test_resolver: RESPONSE/APPLICATION handed to non-controller, non-request owner
t = (repo / "tests/unit/core/ioc/test_resolver.py").read_text()
checks["resolver_test_hands_RESPONSE_to_plain_owner"] = bool(re.search(
    r'token=RESPONSE.*?owner_is_controller=False,\s*is_request_scoped=False,\s*is_durable_scoped=False,\s*\) is response', t, re.S))

# (3) test_exception_filters: REQUEST-scoped provider into default controller, asserts 500 only
t = (repo / "tests/integration/platform/test_exception_filters.py").read_text()
checks["filters_test_composes_request_provider_into_singleton_controller"] = (
    "@Injectable(scope=Scope.REQUEST)\n    class FailingService" in t and '@Controller("/fails")\n    class FailingController' in t
    and "assert response.status_code == 500" in t)

# (4) test_dynamic_modules: re-export only checked via available_providers; two same-token dynamic imports no winner assertion
t = (repo / "tests/unit/core/module/test_dynamic_modules.py").read_text()
checks["dynamic_reexport_only_available_providers"] = ("@Module(imports=[mid_dynamic], exports=[DeepService])" in t
    and "assert DeepService in top_node.available_providers" in t and "resolve(DeepService" not in t.split("def test_dynamic_module_nested_expansion")[1].split("def test_")[0])
seg = t.split("def test_dynamic_module_unique_identities")[1].split("def test_")[0]
checks["dynamic_unique_identities_no_winner_assert"] = ('"use_value": 1' in seg and '"use_value": 2' in seg and "resolve(" not in seg)

# (5) testing builder close(): events == ['shutdown','destroy']; runtime skips before_application_shutdown
checks["testing_test_pins_shutdown_destroy"] = has("tests/unit/testing/test_testing_builder.py", 'assert events == ["shutdown", "destroy"]')
from bustan import Module
from bustan.testing import create_testing_module
events = []
@Module()
class AppModule:
    def before_application_shutdown(self, signal):
        events.append("before")
    def on_application_shutdown(self, signal):
        events.append("shutdown")
    def on_module_destroy(self):
        events.append("destroy")
async def run():
    compiled = await create_testing_module(AppModule).compile()
    await compiled.close()
anyio.run(run)
print("close() events:", events)
checks["runtime_close_skips_before_application_shutdown"] = "before" not in events

# (6) metadata inheritance policy: @Module/@Controller not inherited (tested); @Injectable inherited (untested)
checks["metadata_test_pins_non_inheritance"] = has("tests/unit/core/module/test_metadata.py", "def test_module_metadata_is_not_inherited_by_default")
from bustan import Injectable
from bustan.core.module.metadata import get_module_metadata
@Injectable(scope="request")
class Base: pass
class Derived(Base): pass
binding = normalize_provider(Derived, object)
checks["runtime_injectable_metadata_inherited"] = binding.scope is ProviderScope.REQUEST
@Module()
class BM: pass
class DM(BM): pass
checks["runtime_module_metadata_not_inherited"] = get_module_metadata(DM) is None
import subprocess
grep = subprocess.run(["grep", "-rn", "Injectable", str(repo / "tests/unit/core/module/test_metadata.py")], capture_output=True, text=True)
checks["no_injectable_inheritance_test_in_test_metadata"] = grep.stdout.strip() == ""

for k, v in checks.items():
    print(f"{'ok ' if v else 'NO '} {k}")
all_ok = all(checks.values())
print("RESULT:", "CONFIRMED - every cited test pins the behaviour and the runtime exhibits it" if all_ok else "PARTIAL - see NO lines")
