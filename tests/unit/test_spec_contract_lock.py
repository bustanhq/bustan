"""Regression tests that lock the shared design-spec contract surface."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_ROOT = REPO_ROOT / ".bustan"


def test_shared_contract_owners_remain_explicit() -> None:
    controller_spec = (SPEC_ROOT / "controller.md").read_text()
    execution_context_spec = (SPEC_ROOT / "execution-context.md").read_text()
    providers_spec = (SPEC_ROOT / "providers.md").read_text()
    modules_spec = (SPEC_ROOT / "modules.md").read_text()
    policy_spec = (SPEC_ROOT / "policy.md").read_text()
    roadmap_spec = (SPEC_ROOT / "roadmap.md").read_text()

    assert "## 1.1 Specification ownership" in controller_spec
    assert "`RouteContract` and companion route plans." in controller_spec
    assert "`ArgumentsHost`, `ExecutionContext`, and `Reflector`." in controller_spec
    assert "This document is the authoritative source for public context and metadata APIs." in execution_context_spec
    assert "This document is authoritative for provider lifetime and DI semantics." in providers_spec
    assert "This document is authoritative for policy decorators and `PolicyPlan`." in policy_spec
    assert "module graph introspection is a supported runtime capability." in modules_spec
    assert "* freeze the shape of `RouteContract`, `HandlerBindingPlan`, `ResponsePlan`, `PipelinePlan`, and `PolicyPlan`." in roadmap_spec
    assert "* freeze the public `ArgumentsHost`, `ExecutionContext`, and `Reflector` APIs." in roadmap_spec


def test_canonical_http_pipeline_is_defined_once_and_referenced_elsewhere() -> None:
    controller_spec = (SPEC_ROOT / "controller.md").read_text()
    policy_spec = (SPEC_ROOT / "policy.md").read_text()

    assert controller_spec.count("canonical HTTP request pipeline") >= 2
    assert "This is the canonical HTTP request pipeline for the entire spec set." in controller_spec
    assert "The canonical request pipeline is defined in [controller.md](controller.md)." in policy_spec
