"""Registry: indexed view over discovered manifests."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from biobabel._registry.discovery import (
    DiscoveredManifest,
    DiscoveryError,
    discover,
)
from biobabel.manifest_api import (
    AntiPatternSpec,
    ConceptSpec,
    FunctionContract,
    IdiomSpec,
    PackageManifest,
    WorkflowContract,
)


@dataclass
class Registry:
    """In-memory index over all discovered manifests."""

    packages: dict[str, DiscoveredManifest] = field(default_factory=dict)
    errors: list[DiscoveryError] = field(default_factory=list)

    # Reverse indexes (built once on construction)
    _function_by_id: dict[str, tuple[str, FunctionContract]] = field(default_factory=dict)
    _workflow_by_id: dict[str, tuple[str, WorkflowContract]] = field(default_factory=dict)
    _concept_by_id: dict[str, tuple[str, ConceptSpec]] = field(default_factory=dict)
    _idiom_by_id: dict[str, tuple[str, IdiomSpec]] = field(default_factory=dict)
    _anti_pattern_by_id: dict[str, tuple[str, AntiPatternSpec]] = field(default_factory=dict)

    # Extension reverse-index: parent_function_id → [extending pkg.symbol]
    _extended_by: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    def manifest(self, import_name: str) -> PackageManifest | None:
        entry = self.packages.get(import_name)
        return entry.manifest if entry else None

    def list_packages(
        self,
        *,
        contract_class: str | None = None,
        tier: int | None = None,
        maturity: str | None = None,
    ) -> list[DiscoveredManifest]:
        out = list(self.packages.values())
        if contract_class:
            out = [d for d in out if d.manifest.contract_class == contract_class]
        if tier is not None:
            out = [d for d in out if d.manifest.tier == tier]
        if maturity:
            out = [d for d in out if d.manifest.maturity == maturity]
        return out

    def function(self, symbol_id: str) -> tuple[str, FunctionContract] | None:
        return self._function_by_id.get(symbol_id)

    def workflow(self, workflow_id: str) -> tuple[str, WorkflowContract] | None:
        return self._workflow_by_id.get(workflow_id)

    def concept(self, concept_id: str) -> tuple[str, ConceptSpec] | None:
        return self._concept_by_id.get(concept_id)

    def idiom(self, idiom_id: str) -> tuple[str, IdiomSpec] | None:
        return self._idiom_by_id.get(idiom_id)

    def anti_pattern(self, anti_pattern_id: str) -> tuple[str, AntiPatternSpec] | None:
        return self._anti_pattern_by_id.get(anti_pattern_id)

    def extended_by(self, symbol_id: str) -> list[str]:
        return list(self._extended_by.get(symbol_id, []))

    def all_idioms(self) -> list[tuple[str, IdiomSpec]]:
        return list(self._idiom_by_id.values())

    def all_anti_patterns(self) -> list[tuple[str, AntiPatternSpec]]:
        return list(self._anti_pattern_by_id.values())


def build_registry() -> Registry:
    """Discover all entry points, build a fully indexed registry."""
    successes, errors = discover()
    reg = Registry(errors=list(errors))

    for d in successes:
        reg.packages[d.import_name] = d
        m = d.manifest

        for fn in m.functions:
            reg._function_by_id[fn.id] = (d.import_name, fn)
        for wf in m.workflows:
            reg._workflow_by_id[wf.id] = (d.import_name, wf)
        for c in m.concepts:
            reg._concept_by_id[c.id] = (d.import_name, c)
        for idiom in m.idioms:
            reg._idiom_by_id[idiom.id] = (d.import_name, idiom)
        for ap in m.anti_patterns:
            reg._anti_pattern_by_id[ap.id] = (d.import_name, ap)

    # Build extension reverse index in a second pass — needs full set of imports.
    for d in successes:
        m = d.manifest
        for ext in m.extends:
            for provided in ext.provides:
                if provided.replaces_or_extends:
                    reg._extended_by[provided.replaces_or_extends].append(
                        f"{d.import_name}.{provided.name}"
                    )

    return reg
