"""Group 4 — Concept Layer (3 tools)."""

from __future__ import annotations

from typing import Any

from biobabel._concept.idiom_search import list_idioms_for
from biobabel._registry.builder import Registry
from biobabel.mcp.envelope import error, success


def describe_concept(registry: Registry, *, concept_id: str) -> dict[str, Any]:
    hit = registry.concept(concept_id)
    if hit is None:
        return error(
            "biobabel.describe_concept",
            error_code="not_found",
            message=f"no ConceptSpec with id '{concept_id}'",
        )
    pkg, c = hit
    return success(
        "biobabel.describe_concept",
        summary=f"{c.name} ({c.category})",
        outputs={"package": pkg, "concept": c.model_dump(mode="json")},
    )


def list_idioms(
    registry: Registry,
    *,
    package: str | None = None,
    applicable_to: str | None = None,
    task: str | None = None,
) -> dict[str, Any]:
    hits = list_idioms_for(registry, package=package, applicable_to=applicable_to, task=task)
    return success(
        "biobabel.list_idioms",
        summary=f"{len(hits)} idiom(s)",
        outputs={
            "idioms": [
                {
                    "package": pkg,
                    "id": idiom.id,
                    "name": idiom.name,
                    "applicable_to": list(idiom.applicable_to),
                    "use_case": idiom.typical_use_case,
                }
                for pkg, idiom in hits
            ]
        },
    )


def describe_idiom(registry: Registry, *, idiom_id: str) -> dict[str, Any]:
    hit = registry.idiom(idiom_id)
    if hit is None:
        return error(
            "biobabel.describe_idiom",
            error_code="not_found",
            message=f"no IdiomSpec with id '{idiom_id}'",
        )
    pkg, idiom = hit
    return success(
        "biobabel.describe_idiom",
        summary=idiom.name,
        outputs={"package": pkg, "idiom": idiom.model_dump(mode="json")},
    )
