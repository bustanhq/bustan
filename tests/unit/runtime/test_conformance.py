"""Unit tests for the adapter conformance suite.

Two things are being tested here and they are not the same thing. One is that the suite
covers what it claims to cover, which is checked by enumerating the framework's own
parameter sources, response strategies and versioning strategies and asking the suite
which of them it names. The other is that every adapter passes it, and passes it the
same way, which is what makes the suite worth having.
"""

from __future__ import annotations

import ast
import builtins
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from bustan import conformance as conformance_module
from bustan.adapters.asgi import AsgiAdapter
from bustan.conformance import (
    ADAPTER_NAMES,
    UNCERTIFIED_PARAMETER_SOURCES,
    AdapterConformanceResult,
    ConformanceCase,
    ConformanceRequest,
    ResponseObservation,
    describe_difference,
    evaluate_adapter_conformance,
    load_adapter,
)
from bustan.contracts import AbstractHttpAdapter, AdapterCapabilities, HttpRequest
from bustan.runtime.compiler import ResponseStrategy
from bustan.runtime.params import ParameterSource
from bustan.runtime.versioning import VersioningType

if TYPE_CHECKING:
    from collections.abc import Sequence


@pytest.fixture(scope="module")
def results() -> dict[str, AdapterConformanceResult]:
    """Run the suite once for every adapter, because every test below reads the same run."""

    return {name: evaluate_adapter_conformance(load_adapter(name)) for name in ADAPTER_NAMES}


# The one case whose adapters answer different documents by declaration, so that the two
# tests below exempt that case by name rather than exempting whatever asks to be exempt.
DECLARED_DIVERGENCE = "request_target_keeps_an_encoded_slash_inside_its_segment"


def _declared_divergences() -> set[str]:
    """Return the cases that hold a named adapter to a document of its own."""

    return {
        case.name
        for scenario in conformance_module.SCENARIOS
        for case in scenario.cases
        if case.expected_by_adapter
    }


def _dimensions() -> set[str]:
    return {case.dimension for scenario in conformance_module.SCENARIOS for case in scenario.cases}


def _all_dimensions() -> set[str]:
    return _dimensions() | {
        conformance_module.LIFESPAN_STARTUP_CASE.dimension,
        conformance_module.LIFESPAN_SHUTDOWN_CASE.dimension,
    }


def test_the_suite_covers_every_parameter_source_it_does_not_declare_uncertified() -> None:
    covered = {
        dimension.removeprefix("parameter source: ")
        for dimension in _dimensions()
        if dimension.startswith("parameter source: ")
    }

    assert covered | set(UNCERTIFIED_PARAMETER_SOURCES) == {
        source.value for source in ParameterSource
    }


def test_the_form_body_sources_are_certified_rather_than_declared_uncertified() -> None:
    """The two sources that read a parsed form are answered by cases, not written off."""

    assert UNCERTIFIED_PARAMETER_SOURCES == ()
    assert {"parameter source: file", "parameter source: files"} <= _dimensions()


def test_the_form_body_cases_post_a_form_body() -> None:
    """A case that never sends a form would certify form parsing without exercising it."""

    cases = [
        case
        for scenario in conformance_module.SCENARIOS
        for case in scenario.cases
        if case.dimension in {"parameter source: file", "parameter source: files"}
    ]

    assert len(cases) == 2
    for case in cases:
        assert case.request.method == "POST"
        assert dict(case.request.headers)["content-type"].startswith("multipart/form-data;")
        assert case.request.content


def test_every_adapter_is_certified_on_the_transport_s_own_request_object(
    results: dict[str, AdapterConformanceResult],
) -> None:
    """Both spellings of the request are certified, not only the neutral one.

    The case names the transport's request without naming a transport, so each adapter
    answers it with the object it produces, and each has to reach the same body out of
    it. An adapter whose own request cannot be streamed fails the case here rather than
    failing an application that wrote the annotation the framework recognises.
    """

    for adapter, result in results.items():
        check = next(
            check for check in result.checks if check.name == "parameter_source_native_request"
        )

        assert check.passed, f"{adapter}: {check.detail}"


def test_the_suite_covers_every_response_strategy() -> None:
    covered = {
        dimension.removeprefix("response strategy: ")
        for dimension in _dimensions()
        if dimension.startswith("response strategy: ")
    }

    assert covered == {strategy.value for strategy in ResponseStrategy}


def test_the_suite_covers_every_versioning_strategy() -> None:
    covered = {
        dimension.removeprefix("versioning strategy: ")
        for dimension in _dimensions()
        if dimension.startswith("versioning strategy: ")
    }

    assert covered == {strategy.value for strategy in VersioningType}


def test_the_suite_covers_middleware_exception_filters_and_the_lifespan() -> None:
    assert {"middleware", "exception filter", "lifespan"} <= _all_dimensions()


def test_the_suite_imports_no_web_server_and_no_transports_test_client() -> None:
    """The suite is only worth something if it drives each adapter through its own client."""

    text = _module_source()
    imported = {
        alias.name
        for node in ast.walk(ast.parse(text))
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(ast.parse(text))
        if isinstance(node, ast.ImportFrom) and not node.level
    }

    assert not [name for name in imported if name.split(".")[0] in {"starlette", "uvicorn"}]
    assert not [name for name in imported if "testclient" in name]
    assert "create_test_client()" in text


def _module_source() -> str:
    source = conformance_module.__file__
    assert source is not None
    return Path(source).read_text(encoding="utf-8")


@pytest.mark.parametrize("adapter_name", ADAPTER_NAMES)
def test_every_adapter_passes_the_suite(
    adapter_name: str, results: dict[str, AdapterConformanceResult]
) -> None:
    result = results[adapter_name]
    failures = [f"{check.name}: {check.detail}" for check in result.checks if not check.passed]

    assert failures == []
    assert result.passed
    assert result.adapter == adapter_name


def test_every_adapter_answers_every_case_identically_but_the_one_that_says_otherwise(
    results: dict[str, AdapterConformanceResult],
) -> None:
    """Identical answers everywhere except the case that declares where they cannot be.

    The exempt case is named rather than counted, so a second case reaching for the same
    facility fails here instead of being skipped along with it.
    """

    declared = _declared_divergences()
    baseline_name, *others = ADAPTER_NAMES
    baseline = results[baseline_name].observations()

    assert declared == {DECLARED_DIVERGENCE}
    for name in others:
        for case, observation in results[name].observations().items():
            if case in declared:
                continue
            assert describe_difference(baseline_name, baseline[case], name, observation) == ()


def test_the_case_held_apart_is_answered_differently_and_passed_by_every_adapter(
    results: dict[str, AdapterConformanceResult],
) -> None:
    """The exemption has to be needed, and it has to buy nothing beyond itself.

    Needed, because an exemption covering a case the adapters agree on is a hole in the
    comparison that nothing else would report. And nothing beyond itself, because each
    adapter is still held to the document the case names for it: a declared divergence
    excuses the two answers from matching each other, not from being right.
    """

    baseline_name, *others = ADAPTER_NAMES
    baseline = results[baseline_name].observations()[DECLARED_DIVERGENCE]

    for name in others:
        observation = results[name].observations()[DECLARED_DIVERGENCE]
        assert describe_difference(baseline_name, baseline, name, observation) != ()
    for adapter, result in results.items():
        check = next(check for check in result.checks if check.name == DECLARED_DIVERGENCE)
        assert check.passed, f"{adapter}: {check.detail}"


def test_the_result_reports_capabilities_and_serialises(
    results: dict[str, AdapterConformanceResult],
) -> None:
    report = results["starlette"].to_dict()

    assert report["adapter"] == "starlette"
    assert report["passed"] is True
    assert report["capabilities"] == {
        "supports_host_routing": False,
        "supports_raw_body": True,
        "supports_streaming_responses": True,
        "supports_websocket_upgrade": False,
    }
    checks = cast("tuple[dict[str, object], ...]", report["checks"])
    assert all("observation" in check and "dimension" in check for check in checks)


def test_load_adapter_builds_each_adapter_the_matrix_names() -> None:
    assert [load_adapter(name).name for name in ADAPTER_NAMES] == list(ADAPTER_NAMES)


def test_load_adapter_rejects_unsupported_names() -> None:
    with pytest.raises(ValueError, match="Unsupported adapter 'unknown'"):
        load_adapter("unknown")


def test_describe_difference_names_the_field_and_both_sides() -> None:
    left = ResponseObservation(200, (("content-type", "application/json"),), '{"a":1}')
    right = ResponseObservation(500, (("content-type", "text/plain"),), '{"a":2}')

    assert describe_difference("left", left, "right", right) == (
        "status: left=200, right=500",
        "header content-type: left='application/json', right='text/plain'",
        "body: left='{\"a\":1}', right='{\"a\":2}'",
    )


def test_describe_difference_is_silent_when_two_observations_agree() -> None:
    observation = ResponseObservation(204, (), "")

    assert describe_difference("left", observation, "right", observation) == ()


def test_describe_difference_reports_a_case_only_one_side_observed() -> None:
    observation = ResponseObservation(204, (), "")

    difference = describe_difference("left", observation, "right", None)

    assert len(difference) == 1
    assert "right=None" in difference[0]


def test_a_case_whose_request_raises_is_reported_rather_than_propagated() -> None:
    class BrokenClient:
        def request(self, *_arguments: object, **_options: object) -> object:
            raise ConnectionError("no route to the application")

    case = ConformanceCase(
        name="broken",
        dimension="parameter source: path",
        request=ConformanceRequest(path="/"),
        expected=ResponseObservation(200, (), ""),
    )

    check = conformance_module._run_case(BrokenClient(), case)

    assert not check.passed
    assert check.observation is None
    assert check.detail == "ConnectionError: no route to the application"


def test_a_case_answered_differently_fails_with_the_difference_as_its_detail() -> None:
    case = ConformanceCase(
        name="mismatched",
        dimension="response strategy: standard",
        request=ConformanceRequest(path="/"),
        expected=ResponseObservation(200, (("content-type", "application/json"),), "{}"),
    )

    check = conformance_module._compare(
        case, ResponseObservation(404, (("content-type", "application/json"),), "{}")
    )

    assert not check.passed
    assert check.detail == "status: expected=200, observed=404"


def test_an_adapter_that_cannot_be_built_with_a_lifespan_fails_that_case() -> None:
    """An adapter is handed its lifespan at construction, and the port does not say so."""

    checks = conformance_module._run_lifespan_scenario(_LifespanlessAdapter())

    assert len(checks) == 1
    assert not checks[0].passed
    assert "no lifespan on construction" in checks[0].detail


def test_the_lifespan_cases_fail_when_the_adapter_drops_the_frameworks_lifespan() -> None:
    """The cases are only worth running if they can go red when the module graph never starts."""

    checks = conformance_module._run_lifespan_scenario(_LifespanIgnoringAdapter())

    assert [check.passed for check in checks] == [False, False]
    assert all("module_inits" in check.detail for check in checks)


def test_the_lifespan_scenario_certifies_no_lifespan_the_suite_wrote() -> None:
    """The counters the cases read must be written by the module graph, not by the suite."""

    record = conformance_module.ModuleLifecycleRecord()
    module = conformance_module._build_lifecycle_module(record)

    assert callable(getattr(module, "on_module_init", None))
    assert callable(getattr(module, "on_application_shutdown", None))
    assert record.state() == {"module_inits": 0, "application_shutdowns": 0}
    assert "asynccontextmanager" not in _module_source()


def test_the_suite_imports_no_adapter_that_needs_an_extra_at_module_scope() -> None:
    """Only the kernel is needed to import the suite, so the adapter needing none can run."""

    tree = ast.parse(_module_source())
    module_scope = [node for node in tree.body if isinstance(node, ast.ImportFrom)]

    assert not [
        node for node in module_scope if (node.module or "").startswith("adapters.starlette")
    ]


def test_load_adapter_turns_an_absent_extra_into_an_install_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing extra and an unknown adapter name are different mistakes and read that way."""

    real_import = builtins.__import__

    def refuse(name: str, *arguments: Any, **options: Any) -> Any:
        if name.endswith("adapters.starlette"):
            raise ModuleNotFoundError("No module named 'starlette'", name="starlette")
        return real_import(name, *arguments, **options)

    monkeypatch.setattr(builtins, "__import__", refuse)

    with pytest.raises(ImportError, match=r"bustan\[starlette\]"):
        load_adapter("starlette")


class _LifespanlessAdapter(AbstractHttpAdapter):
    """An adapter whose constructor takes nothing, which is all the port requires."""

    name = "lifespanless"
    capabilities = AdapterCapabilities()

    def from_native_request(self, native_request: object) -> HttpRequest:
        raise NotImplementedError

    def to_native_response(self, response: object) -> object:
        raise NotImplementedError

    def register_routes(self, routes: Sequence[Any]) -> None:
        raise NotImplementedError

    async def start(
        self, port: int, host: str = "127.0.0.1", reload: bool = False, **options: object
    ) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        raise NotImplementedError

    def create_test_client(self) -> object:
        raise NotImplementedError

    def get_instance(self) -> object:
        raise NotImplementedError

    def add_middleware(self, middleware_class: type, **options: object) -> None:
        raise NotImplementedError


class _LifespanIgnoringAdapter(AsgiAdapter):
    """A working adapter that accepts the framework's lifespan and then drops it.

    Everything else about it conforms, so the lifespan cases fail on what they are for
    rather than on the adapter being unable to answer a request at all.
    """

    name = "lifespan-ignoring"

    def __init__(self, *, lifespan: object | None = None) -> None:
        super().__init__()
