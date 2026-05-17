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

    # X:<semantic> tokens are advisory in this layer: biobabel cannot verify
    # adata.X content from the handle alone (the handle stores slot keys, not
    # X dtype). They are filtered out of the state-presence check rather than
    # always reported as missing — see roadmap P0-1 for the rationale.
    missing = [
        r for r in step.requires
        if not r.startswith("X:") and r not in present
    ]
    if not missing:
        return PrereqResult(satisfied=True)

    fixes: list[str] = []
    for slot in missing:
        for _, fn in registry._function_by_id.values():
            if slot in fn.writes:
                fixes.append(fn.id)
                break

    return PrereqResult(satisfied=False, missing=missing, fix_suggestions=fixes)
