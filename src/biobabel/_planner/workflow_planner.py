"""Task → ordered WorkflowSteps.

On a task string, return the matching ``WorkflowContract`` if one was declared
by a registered producer. On a miss, return ``source="none"`` and let the
caller (the LLM) compose a chain from individual ``FunctionContract``s via
``biobabel.search`` / ``biobabel.describe_symbol``.

The planner used to also synthesize an ad-hoc pipeline via BFS over function
``requires/writes`` when no declared workflow matched. That mode duplicated a
job LLMs already do better (they have intent, the BFS only has subset matching
on tokens) — same pattern as the deleted TF-IDF recommender — so it was
removed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from biobabel._registry.builder import Registry


@dataclass
class PlanStep:
    call: str
    requires: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    description: str = ""
    optional: bool = False


@dataclass
class Plan:
    source: str                     # "workflow_contract" | "none"
    workflow_id: str = ""
    steps: list[PlanStep] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def plan_workflow(
    registry: Registry,
    *,
    task: str,
    input_type: str = "AnnData",
    current_state: dict[str, list[str]] | None = None,
    package_hint: str | None = None,
) -> Plan:
    task_l = task.lower()
    for _, (_, wc) in registry._workflow_by_id.items():
        if any(intent.lower() in task_l for intent in wc.intent) or wc.description.lower() in task_l:
            return Plan(
                source="workflow_contract",
                workflow_id=wc.id,
                steps=[
                    PlanStep(
                        call=s.call,
                        requires=list(s.requires),
                        writes=list(s.writes),
                        description=s.description,
                        optional=s.optional,
                    )
                    for s in wc.steps
                ],
                notes=[f"Matched known workflow '{wc.id}'."],
            )

    return Plan(
        source="none",
        notes=[
            "No declared WorkflowContract matched this task. "
            "Use biobabel.search and biobabel.describe_symbol to assemble a pipeline."
        ],
    )
