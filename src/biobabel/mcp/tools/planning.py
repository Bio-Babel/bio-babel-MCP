"""Group 3 — Planning (2 tools).

Package recommendation is intentionally *not* an MCP tool: the LLM ranks
packages itself from the signals surfaced by ``biobabel.list_packages``
(triggers, task_tags, capabilities, not_when, foundation, ...). biobabel
does not impose a hand-tuned scoring formula.
"""

from __future__ import annotations

from typing import Any

from biobabel._planner.prereq_check import check_prerequisites as _check
from biobabel._planner.workflow_planner import PlanStep
from biobabel._planner.workflow_planner import plan_workflow as _plan
from biobabel._registry.builder import Registry
from biobabel._runtime.session import SessionStore
from biobabel.mcp.envelope import error, success


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
