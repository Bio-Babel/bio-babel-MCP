"""Planner: recommender + workflow planner + prereq check."""

from __future__ import annotations

from biobabel._planner.prereq_check import check_prerequisites
from biobabel._planner.recommender import recommend, search_text
from biobabel._planner.workflow_planner import PlanStep, plan_workflow
from biobabel._runtime.session import AdataHandle


def test_recommend_finds_monocle_for_pseudotime(registry):
    recs = recommend(registry, "pseudotime trajectory on single-cell data", k=3)
    assert recs
    assert recs[0].package == "monocle3_py"


def test_recommend_finds_grid_for_plotting_package(registry):
    recs = recommend(registry, "build a plotting package on top of grid", k=3)
    assert recs
    assert recs[0].package == "grid_py"


def test_plan_workflow_hits_known_contract(registry):
    plan = plan_workflow(registry, task="pseudotime trajectory")
    assert plan.source == "workflow_contract"
    assert plan.workflow_id == "monocle3.basic_trajectory"
    assert len(plan.steps) >= 1


def test_search_text_returns_idioms(registry):
    hits = search_text(registry, "push draw pop")
    kinds = {h["kind"] for h in hits}
    assert "idiom" in kinds


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
