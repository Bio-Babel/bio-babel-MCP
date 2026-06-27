"""Contract discovery and lookup tools."""

from __future__ import annotations

from typing import Any

from biobabel._registry.builder import Registry
from biobabel.manifest_api import ContractClass
from biobabel.mcp.envelope import error, success


def list_packages(
    registry: Registry,
    *,
    contract_class: ContractClass | None = None,
    tier: int | None = None,
    maturity: str | None = None,
) -> dict[str, Any]:
    rows = []
    for d in registry.list_packages(contract_class=contract_class, tier=tier, maturity=maturity):
        m = d.manifest
        rows.append(
            {
                "import_name": d.import_name,
                "distribution": d.distribution,
                "version": d.distribution_version,
                "contract_class": m.contract_class,
                "tier": m.tier,
                "maturity": m.maturity,
                "display_name": m.display_name,
                "foundation": list(m.foundation),
            }
        )
    return success(
        "biobabel.list_packages",
        summary=f"{len(rows)} package(s) registered",
        outputs={"packages": rows, "errors": [e.__dict__ for e in registry.errors]},
    )


def describe_package(registry: Registry, *, import_name: str) -> dict[str, Any]:
    d = registry.packages.get(import_name)
    if d is None:
        return error(
            "biobabel.describe_package",
            error_code="not_found",
            message=f"no package registered under import name '{import_name}'",
        )
    manifest = d.manifest.model_dump(mode="json")
    # The full symbol contracts dominate the payload (hundreds of symbols, each with
    # description/parameters/examples/failure_fixes/...). Return a lightweight symbol
    # INDEX here and let the agent pull full detail on demand via describe_symbol.
    # Concepts/idioms/anti_patterns are kept in full: they are the upfront "how-to"
    # knowledge and have no drill-down tool of their own.
    symbols = manifest.get("symbols") or []
    manifest["symbols"] = [
        {k: s[k] for k in ("id", "kind", "signature", "purpose") if s.get(k) is not None}
        for s in symbols
    ]
    manifest["symbol_count"] = len(symbols)
    return success(
        "biobabel.describe_package",
        summary=(
            f"{d.manifest.display_name} ({d.manifest.contract_class}) — "
            f"{len(symbols)} symbols (indexed; call describe_symbol(symbol_id) for full detail)"
        ),
        outputs={"manifest": manifest},
    )


def list_workflows(registry: Registry, *, package: str | None = None, task_tag: str | None = None) -> dict[str, Any]:
    rows = []
    for pkg, workflow in registry.list_workflows(package=package):
        if task_tag and task_tag not in workflow.task_tags:
            continue
        rows.append(
            {
                "package": pkg,
                "id": workflow.id,
                "title": workflow.title,
                "task_tags": list(workflow.task_tags),
                "description": workflow.description,
            }
        )
    return success("biobabel.list_workflows", summary=f"{len(rows)} workflow(s)", outputs={"workflows": rows})


def describe_workflow(registry: Registry, *, workflow_id: str) -> dict[str, Any]:
    hit = registry.workflow(workflow_id)
    if hit is None:
        return error(
            "biobabel.describe_workflow",
            error_code="not_found",
            message=f"no WorkflowContract with id '{workflow_id}'",
        )
    pkg, workflow = hit
    return success(
        "biobabel.describe_workflow",
        summary=workflow.title or workflow.id,
        outputs={"package": pkg, "workflow": workflow.model_dump(mode="json")},
    )


def list_symbols(
    registry: Registry,
    *,
    package: str | None = None,
    kind: str | None = None,
    query: str | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    """Find symbol contracts. With Tier-1 covering ~1.2k symbols, a bare list is
    a context bomb, so `query` does a case-insensitive substring match over
    id/signature/summary (the registry-lookup pattern) and `limit` caps the
    rows. Narrow with `query=` before reading; use `describe_symbol` for one."""
    q = (query or "").strip().lower()
    rows = []
    for pkg, symbol in registry.list_symbols(package=package):
        if kind and symbol.kind != kind:
            continue
        if q and q not in f"{symbol.id}\n{symbol.signature}\n{symbol.description or symbol.purpose}".lower():
            continue
        rows.append(
            {
                "package": pkg,
                "id": symbol.id,
                "kind": symbol.kind,
                "signature": symbol.signature,
                "summary": symbol.description or symbol.purpose,
            }
        )
    if q:  # exact name hits first, so the limit keeps the most relevant rows
        rows.sort(key=lambda r: 0 if q in r["id"].lower() else 1)
    total = len(rows)
    rows = rows[: max(1, limit)]
    note = f"{total} symbol(s)"
    if total > len(rows):
        note += f"; showing {len(rows)} — narrow with query= or raise limit="
    return success("biobabel.list_symbols", summary=note, outputs={"symbols": rows, "total": total})


def describe_symbol(registry: Registry, *, symbol_id: str) -> dict[str, Any]:
    hit = registry.symbol(symbol_id)
    if hit is None:
        return error(
            "biobabel.describe_symbol",
            error_code="not_found",
            message=f"no SymbolContract with id '{symbol_id}'",
        )
    pkg, symbol = hit
    return success(
        "biobabel.describe_symbol",
        summary=symbol.signature or symbol.id,
        outputs={"package": pkg, "symbol": symbol.model_dump(mode="json")},
    )


def list_templates(registry: Registry, *, package: str | None = None, task_tag: str | None = None) -> dict[str, Any]:
    rows = []
    for pkg, template in registry.list_templates(package=package):
        if task_tag and task_tag not in template.task_tags:
            continue
        rows.append(
            {
                "package": pkg,
                "id": template.id,
                "path": template.path,
                "task_tags": list(template.task_tags),
                "description": template.description,
            }
        )
    return success("biobabel.list_templates", summary=f"{len(rows)} template(s)", outputs={"templates": rows})


def describe_template(registry: Registry, *, template_id: str) -> dict[str, Any]:
    hit = registry.template(template_id)
    if hit is None:
        return error(
            "biobabel.describe_template",
            error_code="not_found",
            message=f"no TemplateSpec with id '{template_id}'",
        )
    pkg, template = hit
    return success(
        "biobabel.describe_template",
        summary=template.description or template.id,
        outputs={"package": pkg, "template": template.model_dump(mode="json")},
    )
