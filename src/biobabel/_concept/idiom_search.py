"""List idioms applicable to a package / concept / task."""

from __future__ import annotations

from biobabel._registry.builder import Registry
from biobabel.manifest_api import IdiomSpec


def list_idioms_for(
    registry: Registry,
    *,
    package: str | None = None,
    applicable_to: str | None = None,
    task: str | None = None,
) -> list[tuple[str, IdiomSpec]]:
    out: list[tuple[str, IdiomSpec]] = []
    task_l = task.lower() if task else ""
    for pkg, idiom in registry.all_idioms():
        if package and pkg != package:
            continue
        if applicable_to and applicable_to not in idiom.applicable_to:
            continue
        if task_l and task_l not in idiom.description.lower() and task_l not in idiom.typical_use_case.lower():
            continue
        out.append((pkg, idiom))
    return out
