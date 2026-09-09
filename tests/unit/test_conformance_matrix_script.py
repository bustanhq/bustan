"""Unit tests for the adapter conformance matrix script."""

from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

from bustan.conformance import (
    AdapterConformanceResult,
    ConformanceCase,
    ConformanceCheck,
    ConformanceRequest,
    ResponseObservation,
)
from bustan.runtime.adapter import AdapterCapabilities


def test_the_matrix_passes_over_every_adapter_it_knows(capsys) -> None:
    matrix = _load_matrix_module()

    exit_code = matrix.main([])

    assert exit_code == 0
    assert "every case passed and every adapter answered identically" in capsys.readouterr().out


def test_the_success_line_over_the_live_suite_matches_what_that_suite_narrows(capsys) -> None:
    # The suite may or may not contain a narrowed case, and both states are correct, so
    # what is pinned here is that the line agrees with the suite it was printed for.
    matrix = _load_matrix_module()

    assert matrix.main([]) == 0

    line = capsys.readouterr().out.splitlines()[-1]
    narrowed = matrix._narrowed_cases(matrix._suite_cases())
    if not narrowed:
        assert line.endswith("every case passed and every adapter answered identically.")
    else:
        assert ", except that " in line
        for case in narrowed:
            assert case.name in line
            for member in case.diverging_body_members:
                assert member in line


def test_a_run_narrowing_nothing_claims_identical_answers_without_qualifying_it() -> None:
    matrix = _load_matrix_module()

    line = matrix._success_line(
        ("starlette", "asgi"), 40, matrix._narrowed_cases((_case("first"), _case("second")))
    )

    assert line == (
        "40 conformance cases over starlette, asgi: "
        "every case passed and every adapter answered identically."
    )


def test_a_narrowed_case_is_named_in_the_success_line_with_the_member_it_steps_over() -> None:
    matrix = _load_matrix_module()
    cases = (_case("compared"), _case("narrowed", diverging=("detail",)))

    line = matrix._success_line(("starlette", "asgi"), 40, matrix._narrowed_cases(cases))

    assert line == (
        "40 conformance cases over starlette, asgi: "
        "every case passed and every adapter answered identically, "
        "except that 1 case narrows the comparison: narrowed steps over detail."
    )


def test_every_narrowed_case_and_every_member_it_steps_over_is_named() -> None:
    matrix = _load_matrix_module()
    cases = (
        _case("first", diverging=("detail", "title")),
        _case("compared"),
        _case("second", diverging=("detail", "title", "type")),
    )

    line = matrix._success_line(("starlette", "asgi"), 7, matrix._narrowed_cases(cases))

    assert line == (
        "7 conformance cases over starlette, asgi: "
        "every case passed and every adapter answered identically, "
        "except that 2 cases narrow the comparison: "
        "first steps over detail and title; second steps over detail, title and type."
    )


def test_only_the_cases_that_name_a_diverging_member_are_reported_as_narrowed() -> None:
    matrix = _load_matrix_module()
    narrowed = _case("narrowed", diverging=("detail",))

    assert matrix._narrowed_cases((_case("compared"), narrowed, _case("also_compared"))) == (
        narrowed,
    )


def test_the_matrix_refuses_to_run_with_one_adapter(capsys) -> None:
    matrix = _load_matrix_module()

    exit_code = matrix.main(["--adapters", "starlette"])

    assert exit_code == 1
    assert "at least two adapters" in capsys.readouterr().err


def test_the_matrix_reports_an_adapter_it_does_not_know(capsys) -> None:
    matrix = _load_matrix_module()

    exit_code = matrix.main(["--adapters", "starlette", "imaginary"])

    assert exit_code == 1
    assert "Unsupported adapter 'imaginary'" in capsys.readouterr().err


def test_a_difference_names_the_case_both_adapters_and_the_field() -> None:
    matrix = _load_matrix_module()
    results = {
        "starlette": _result("starlette", _observation(200, '{"a":1}')),
        "asgi": _result("asgi", _observation(500, '{"a":2}')),
    }

    differences = matrix._differences(("starlette", "asgi"), results)

    body_difference = (
        "response_strategy_standard: starlette and asgi differ - "
        "body: starlette='{\"a\":1}', asgi='{\"a\":2}'"
    )
    assert differences == [
        "response_strategy_standard: starlette and asgi differ - status: starlette=200, asgi=500",
        body_difference,
    ]


def test_a_case_only_one_adapter_ran_is_a_difference() -> None:
    matrix = _load_matrix_module()
    results = {
        "starlette": _result("starlette", _observation(200, "")),
        "asgi": AdapterConformanceResult(
            adapter="asgi", capabilities=AdapterCapabilities(), checks=()
        ),
    }

    differences = matrix._differences(("starlette", "asgi"), results)

    assert differences == ["response_strategy_standard: run by one of starlette, asgi and not both"]


def test_a_case_both_adapters_fail_the_same_way_is_still_reported() -> None:
    matrix = _load_matrix_module()
    observation = _observation(500, "")
    results = {
        "starlette": _result("starlette", observation, passed=False),
        "asgi": _result("asgi", observation, passed=False),
    }

    assert matrix._differences(("starlette", "asgi"), results) == []
    assert matrix._failures(results) == [
        "response_strategy_standard: starlette failed the case: status: expected=200, observed=500",
        "response_strategy_standard: asgi failed the case: status: expected=200, observed=500",
    ]


def _case(name: str, *, diverging: tuple[str, ...] = ()) -> ConformanceCase:
    """Build a case for the reporting to describe, rather than borrowing one the suite runs.

    The suite's own membership is not this file's subject and changes with the adapters'
    behaviour, so a test that read a narrowed case out of it would be asserting against a
    moving target.
    """

    return ConformanceCase(
        name=name,
        dimension="reporting",
        request=ConformanceRequest(path=f"/{name}"),
        expected=_observation(200, "{}"),
        diverging_body_members=diverging,
    )


def _observation(status_code: int, body: str) -> ResponseObservation:
    return ResponseObservation(
        status_code=status_code,
        headers=(("content-type", "application/json"),),
        body=body,
    )


def _result(
    adapter: str, observation: ResponseObservation, *, passed: bool = True
) -> AdapterConformanceResult:
    return AdapterConformanceResult(
        adapter=adapter,
        capabilities=AdapterCapabilities(),
        checks=(
            ConformanceCheck(
                name="response_strategy_standard",
                passed=passed,
                detail="status: expected=200, observed=500",
                dimension="response strategy: standard",
                observation=observation,
            ),
        ),
    )


def _load_matrix_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "conformance_matrix.py"
    module_spec = spec_from_file_location("conformance_matrix", script_path)
    assert module_spec is not None
    assert module_spec.loader is not None

    module = module_from_spec(module_spec)
    # Registered before execution because the script resolves its postponed annotations
    # through sys.modules, and a module absent from it cannot be resolved against.
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module
