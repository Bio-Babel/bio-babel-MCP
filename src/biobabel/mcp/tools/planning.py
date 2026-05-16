"""Group 3 — Planning (3 tools)."""

from __future__ import annotations

from typing import Any

from biobabel._planner.prereq_check import check_prerequisites as _check
from biobabel._planner.recommender import recommend as _recommend
from biobabel._planner.workflow_planner import PlanStep, plan_workflow as _plan
from biobabel._registry.builder import Registry
from biobabel._runtime.session import SessionStore
from biobabel.mcp.envelope import error, success


def recommend(registry: Registry, *, task: str, k: int = 3) -> dict[str, Any]:
    if not task.strip():
        return error("biobabel.recommend", error_code="empty_task", message="task required")
    recs = _recommend(registry, task, k=k)
    return success(
        "biobabel.recommend",
        summary=f"{len(recs)} recommendation(s)",
        outputs={"recommendations": [r.__dict__ for r in recs]},
    )


def plan_workflow(
    registry: Registry,
    *,
    task: str,
    input_type: str = "AnnData",
    current_state: dict[str, list[str]] | None = None,
    package_hint: str | None = None,
) -> dict[str, Any]:
    plan = _plan(
        registry,
        task=task,
        input_type=input_type,
        current_state=current_state,
        package_hint=package_hint,
    )
    return success(
        "biobabel.plan_workflow",
        summary=f"source={plan.source}, {len(plan.steps)} steps",
        outputs={
            "source": plan.source,
            "workflow_id": plan.workflow_id,
            "steps": [s.__dict__ for s in plan.steps],
            "notes": plan.notes,
        },
    )


def check_prerequisites(
    registry: Registry,
    sessions: SessionStore,
    *,
    session_id: str,
    adata_id: str,
    step: dict[str, Any],
) -> dict[str, Any]:
    sess = sessions.get(session_id)
    if sess is None:
        return error(
            "biobabel.check_prerequisites",
            error_code="session_not_found",
            message=f"no session '{session_id}'",
        )
    adata = sess.get_adata(adata_id)
    if adata is None:
        return error(
            "biobabel.check_prerequisites",
            error_code="adata_not_found",
            message=f"no adata '{adata_id}' in session",
        )
    ps = PlanStep(
        call=step.get("call", ""),
        requires=list(step.get("requires", [])),
        writes=list(step.get("writes", [])),
    )
    result = _check(registry, ps, adata)
    return success(
        "biobabel.check_prerequisites",
        summary="satisfied" if result.satisfied else f"{len(result.missing)} missing",
        outputs={
            "satisfied": result.satisfied,
            "missing": result.missing,
            "fix_suggestions": result.fix_suggestions,
        },
    )
