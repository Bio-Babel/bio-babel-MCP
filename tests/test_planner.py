"""Planner: workflow planner + prereq check + cross-package search."""

from __future__ import annotations

import pytest

from biobabel._planner.prereq_check import check_prerequisites
from biobabel._planner.search import search_text
from biobabel._planner.workflow_planner import PlanStep, plan_workflow
from biobabel._runtime.session import AdataHandle


def test_plan_workflow_hits_known_contract(registry):
    plan = plan_workflow(registry, task="pseudotime trajectory")
    assert plan.source == "workflow_contract"
    assert plan.workflow_id == "monocle3.basic_trajectory"
    assert len(plan.steps) >= 1


def test_plan_workflow_misses_return_source_none(registry):
    """No declared workflow matches → planner does NOT try to synthesize one
    (the BFS mode was removed). It returns source='none' with a note pointing
    the caller at search + describe_symbol."""
    plan = plan_workflow(registry, task="completely unrelated task xyzzy")
    assert plan.source == "none"
    assert plan.steps == []
    assert plan.workflow_id == ""
    assert any("biobabel.search" in n for n in plan.notes)


def test_search_text_returns_idioms(registry):
    hits = search_text(registry, "push draw pop")
    kinds = {h["kind"] for h in hits}
    assert "idiom" in kinds


def test_search_text_is_sorted_by_package_kind_id(registry):
    hits = search_text(registry, "viewport grob unit")
    keys = [(h["package"], h["kind"], h["id"]) for h in hits]
    assert keys == sorted(keys), "search_text must return deterministic order"


def test_search_text_rejects_unknown_kind(registry):
    with pytest.raises(ValueError, match="unknown search kinds"):
        search_text(registry, "anything", kinds=["function", "bogus"])


def test_check_prerequisites_satisfied():
    adata = AdataHandle(
        adata_id="a",
        obs_keys=["Size_Factor"],
        obsm_keys=[],
        var_keys=[],
        uns_keys=[],
        layers=[],
    )
    step = PlanStep(call="monocle3.preprocess_cds", requires=["obs.Size_Factor"])
    # registry is not strictly needed in this case (no missing slots)
    from biobabel._registry.builder import Registry
    result = check_prerequisites(Registry(), step, adata)
    assert result.satisfied


def test_check_prerequisites_missing_returns_fix(registry):
    adata = AdataHandle(
        adata_id="a",
        obs_keys=[],
        obsm_keys=[],
        var_keys=[],
        uns_keys=[],
        layers=[],
    )
    step = PlanStep(call="monocle3.preprocess_cds", requires=["obs.Size_Factor"])
    result = check_prerequisites(registry, step, adata)
    assert not result.satisfied
    assert "obs.Size_Factor" in result.missing
    # Fix suggestion should reach for the function that writes Size_Factor
    assert any("size_factor" in s.lower() for s in result.fix_suggestions)


def test_check_prerequisites_x_semantic_is_advisory_not_missing(registry):
    """``X:raw_counts`` is a semantic constraint on adata.X content; it
    cannot be verified from an ``AdataHandle`` (which tracks slot keys,
    not X dtype). Pre-fix, the planner flattened it into the phantom
    state slot ``X.raw_counts`` and reported it missing on every check.
    Lock that bug shut: the token must be silently dropped from the
    state-presence check, while real obs/obsm/var/etc misses still
    surface."""
    fn = registry.function("monocle3.preprocess_cds")
    assert fn is not None
    _, contract = fn
    # The function in the registry exercises the legacy-dict absorption,
    # so this also verifies X:raw_counts survives the validator round trip.
    assert "X:raw_counts" in contract.requires

    adata = AdataHandle(
        adata_id="a",
        obs_keys=["Size_Factor"],     # state prereq satisfied
        obsm_keys=[],
        var_keys=[],
        uns_keys=[],
        layers=[],
    )
    step = PlanStep(call="monocle3.preprocess_cds", requires=list(contract.requires))
    result = check_prerequisites(registry, step, adata)
    assert result.satisfied, (
        f"X:raw_counts must not block a satisfied prereq; "
        f"got missing={result.missing}"
    )
