"""Task → ordered WorkflowSteps. Either return a known WorkflowContract or
build an ad-hoc chain via state-graph BFS over function requires/writes.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from biobabel._registry.builder import Registry
from biobabel.manifest_api import (
    FunctionContract,
    WorkflowContract,
    WorkflowStep,
)


@dataclass
class PlanStep:
    call: str
    requires: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    description: str = ""
    optional: bool = False


@dataclass
class Plan:
    source: str                     # "workflow_contract" | "adhoc_bfs" | "none"
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
    # 1. Try direct WorkflowContract match
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

    # 2. Ad-hoc BFS over functions: find a chain whose terminal `writes` mentions the task
    candidates = _collect_candidates(registry, task, package_hint)
    if not candidates:
        return Plan(source="none", notes=["No workflows nor candidate functions matched the task."])

    chain = _bfs_chain(candidates, current_state or {})
    if not chain:
        return Plan(
            source="adhoc_bfs",
            notes=["BFS could not assemble a chain; consider checking failure_fixes manually."],
        )

    return Plan(
        source="adhoc_bfs",
        steps=[
            PlanStep(
                call=fn.id,
                requires=_flatten_state(fn.requires),
                writes=_flatten_state(fn.writes),
                description=fn.description,
            )
            for fn in chain
        ],
        notes=["Assembled via BFS over function requires/writes."],
    )


def _collect_candidates(
    registry: Registry, task: str, package_hint: str | None
) -> list[FunctionContract]:
    task_l = task.lower()
    fns: list[FunctionContract] = []
    for pkg, fn in registry._function_by_id.values():
        if package_hint and pkg != package_hint:
            continue
        if any(intent.lower() in task_l or task_l in intent.lower() for intent in fn.intent):
            fns.append(fn)
            continue
        if task_l in fn.description.lower():
            fns.append(fn)
    return fns


def _bfs_chain(candidates: list[FunctionContract], current_state: dict[str, list[str]]) -> list[FunctionContract]:
    """Simple BFS: greedy ordering by satisfied prerequisites."""
    remaining = list(candidates)
    state: set[str] = set()
    for slot, keys in current_state.items():
        for k in keys:
            state.add(f"{slot}.{k}")

    chain: list[FunctionContract] = []
    progress = True
    while remaining and progress:
        progress = False
        for fn in list(remaining):
            need = set(_flatten_state(fn.requires))
            if need.issubset(state) or not need:
                chain.append(fn)
                for w in _flatten_state(fn.writes):
                    state.add(w)
                remaining.remove(fn)
                progress = True
                break
    return chain


def _flatten_state(d: dict) -> list[str]:
    """Flatten `{adata: {obs: [x, y]}}` → `['obs.x', 'obs.y']`."""
    out: list[str] = []
    if not isinstance(d, dict):
        return out
    # If the dict is keyed by container ("adata", "df"), descend one level
    container_keys = {"adata", "df", "anndata", "dataframe"}
    inner = d.get("adata") or d.get("df") or d
    if isinstance(inner, dict):
        for slot, keys in inner.items():
            if slot in container_keys:
                continue
            if isinstance(keys, list):
                out.extend(f"{slot}.{k}" for k in keys)
            elif isinstance(keys, str):
                out.append(f"{slot}.{keys}")
    return out
