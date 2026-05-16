"""check_prerequisites: validate a step against an adata snapshot."""

from __future__ import annotations

from dataclasses import dataclass, field

from biobabel._planner.workflow_planner import PlanStep
from biobabel._registry.builder import Registry
from biobabel._runtime.session import AdataHandle


@dataclass
class PrereqResult:
    satisfied: bool
    missing: list[str] = field(default_factory=list)
    fix_suggestions: list[str] = field(default_factory=list)


def check_prerequisites(
    registry: Registry,
    step: PlanStep,
    adata: AdataHandle,
) -> PrereqResult:
    present: set[str] = set()
    for key in adata.obs_keys:
        present.add(f"obs.{key}")
    for key in adata.obsm_keys:
        present.add(f"obsm.{key}")
    for key in adata.var_keys:
        present.add(f"var.{key}")
    for key in adata.uns_keys:
        present.add(f"uns.{key}")
    for key in adata.layers:
        present.add(f"layers.{key}")

    missing = [r for r in step.requires if r not in present]
    if not missing:
        return PrereqResult(satisfied=True)

    # Look up fix suggestions by inspecting any function that writes the missing slot.
    fixes: list[str] = []
    for slot in missing:
        for _, fn in registry._function_by_id.values():
            writes = _flatten_state(fn.writes)
            if slot in writes:
                fixes.append(fn.id)
                break

    return PrereqResult(satisfied=False, missing=missing, fix_suggestions=fixes)


def _flatten_state(d: dict) -> list[str]:
    out: list[str] = []
    if not isinstance(d, dict):
        return out
    inner = d.get("adata") or d.get("df") or d
    if isinstance(inner, dict):
        for slot, keys in inner.items():
            if isinstance(keys, list):
                out.extend(f"{slot}.{k}" for k in keys)
            elif isinstance(keys, str):
                out.append(f"{slot}.{keys}")
    return out
