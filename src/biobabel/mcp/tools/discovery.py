"""Group 1 — Discovery (5 tools)."""

from __future__ import annotations

from typing import Any

from biobabel._registry.builder import Registry
from biobabel._planner.recommender import search_text
from biobabel.mcp.envelope import error, success


def list_packages(
    registry: Registry,
    *,
    contract_class: str | None = None,
    tier: int | None = None,
    maturity: str | None = None,
) -> dict[str, Any]:
    items = registry.list_packages(contract_class=contract_class, tier=tier, maturity=maturity)
    rows = [
        {
            "import_name": d.import_name,
            "distribution": d.distribution,
            "version": d.distribution_version,
            "contract_class": d.manifest.contract_class,
            "tier": d.manifest.tier,
            "maturity": d.manifest.maturity,
            "display_name": d.manifest.display_name,
        }
        for d in items
    ]
    return success(
        "biobabel.list_packages",
        summary=f"{len(rows)} package(s) registered",
        outputs={"packages": rows, "errors": [e.__dict__ for e in registry.errors]},
    )


def search(registry: Registry, *, query: str, kinds: list[str] | None = None) -> dict[str, Any]:
    if not query.strip():
        return error("biobabel.search", error_code="empty_query", message="query must be non-empty")
    hits = search_text(registry, query, kinds=kinds or ["function", "concept", "idiom", "recipe"])
    return success("biobabel.search", summary=f"{len(hits)} hit(s)", outputs={"hits": hits})


def describe_package(registry: Registry, *, import_name: str) -> dict[str, Any]:
    d = registry.packages.get(import_name)
    if d is None:
        return error(
            "biobabel.describe_package",
            error_code="not_found",
            message=f"no package registered under import name '{import_name}'",
        )
    m = d.manifest.model_dump(mode="json")
    pruned = _prune_by_class(m, d.manifest.contract_class)
    return success(
        "biobabel.describe_package",
        summary=f"{d.manifest.display_name} ({d.manifest.contract_class})",
        outputs={"manifest": pruned},
    )


def describe_symbol(registry: Registry, *, symbol_id: str) -> dict[str, Any]:
    hit = registry.function(symbol_id)
    if hit is None:
        return error(
            "biobabel.describe_symbol",
            error_code="not_found",
            message=f"no FunctionContract with id '{symbol_id}'",
        )
    pkg, fn = hit
    return success(
        "biobabel.describe_symbol",
        summary=f"{symbol_id} :: {fn.execution_class}",
        outputs={
            "package": pkg,
            "function": fn.model_dump(mode="json"),
            "extended_by": registry.extended_by(symbol_id),
        },
    )


def describe_workflow(registry: Registry, *, workflow_id: str) -> dict[str, Any]:
    hit = registry.workflow(workflow_id)
    if hit is None:
        return error(
            "biobabel.describe_workflow",
            error_code="not_found",
            message=f"no WorkflowContract with id '{workflow_id}'",
        )
    pkg, wc = hit
    return success(
        "biobabel.describe_workflow",
        summary=f"{workflow_id} ({len(wc.steps)} steps)",
        outputs={"package": pkg, "workflow": wc.model_dump(mode="json")},
    )


def _prune_by_class(m: dict, contract_class: str) -> dict:
    drop = set()
    if contract_class == "analysis":
        drop = {"concepts", "idioms", "anti_patterns", "compositions"}
    elif contract_class == "grammar":
        drop = {"workflows"}
    return {k: v for k, v in m.items() if k not in drop or v}
