"""Registry: indexed view over discovered manifests + detectors."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from biobabel._registry.discovery import (
    DiscoveredDetector,
    DiscoveredManifest,
    DiscoveryError,
    discover,
    discover_detectors,
)
from biobabel.manifest_api import (
    AntiPatternSpec,
    ConceptSpec,
    FunctionContract,
    IdiomSpec,
    PackageManifest,
    WorkflowContract,
)


def _record_duplicate(
    errors: list[DiscoveryError],
    *,
    kind_label: str,
    key: str,
    keeper_distribution: str,
    skipped_distribution: str,
) -> None:
    """Append a ``DiscoveryError(kind='duplicate')`` describing a clash.

    The first registration wins; the colliding registration is skipped so the
    rest of its host manifest can still register what doesn't clash.
    """
    errors.append(
        DiscoveryError(
            name=key,
            distribution=skipped_distribution,
            error=(
                f"duplicate {kind_label} {key!r}: first registered by "
                f"{keeper_distribution!r}, now also declared by "
                f"{skipped_distribution!r} — keeping first, ignoring second"
            ),
            kind="duplicate",
        )
    )


@dataclass
class Registry:
    """In-memory index over all discovered manifests and detectors."""

    packages: dict[str, DiscoveredManifest] = field(default_factory=dict)
    detectors: dict[str, DiscoveredDetector] = field(default_factory=dict)
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

    def detector(self, detector_id: str) -> DiscoveredDetector | None:
        return self.detectors.get(detector_id)

    def extended_by(self, symbol_id: str) -> list[str]:
        return list(self._extended_by.get(symbol_id, []))

    def all_idioms(self) -> list[tuple[str, IdiomSpec]]:
        return list(self._idiom_by_id.values())

    def all_anti_patterns(self) -> list[tuple[str, AntiPatternSpec]]:
        return list(self._anti_pattern_by_id.values())


def build_registry() -> Registry:
    """Discover all entry points (manifests + detectors), build a fully indexed registry.

    Collisions (two distributions declaring the same identifier) are recorded
    as ``DiscoveryError(kind="duplicate")`` rather than silently
    last-write-wins. The first registration keeps the slot; the colliding
    registration is skipped. ``biobabel.health`` surfaces these to the user.
    """
    manifest_successes, manifest_errors = discover()
    detector_successes, detector_errors = discover_detectors()
    reg = Registry(errors=list(manifest_errors) + list(detector_errors))

    for d in manifest_successes:
        if d.import_name in reg.packages:
            _record_duplicate(
                reg.errors,
                kind_label="package import_name",
                key=d.import_name,
                keeper_distribution=reg.packages[d.import_name].distribution,
                skipped_distribution=d.distribution,
            )
            continue

        reg.packages[d.import_name] = d
        m = d.manifest

        for fn in m.functions:
            if fn.id in reg._function_by_id:
                existing_pkg, _ = reg._function_by_id[fn.id]
                _record_duplicate(
                    reg.errors,
                    kind_label="function id",
                    key=fn.id,
                    keeper_distribution=reg.packages[existing_pkg].distribution,
                    skipped_distribution=d.distribution,
                )
                continue
            reg._function_by_id[fn.id] = (d.import_name, fn)

        for wf in m.workflows:
            if wf.id in reg._workflow_by_id:
                existing_pkg, _ = reg._workflow_by_id[wf.id]
                _record_duplicate(
                    reg.errors,
                    kind_label="workflow id",
                    key=wf.id,
                    keeper_distribution=reg.packages[existing_pkg].distribution,
                    skipped_distribution=d.distribution,
                )
                continue
            reg._workflow_by_id[wf.id] = (d.import_name, wf)

        for c in m.concepts:
            if c.id in reg._concept_by_id:
                existing_pkg, _ = reg._concept_by_id[c.id]
                _record_duplicate(
                    reg.errors,
                    kind_label="concept id",
                    key=c.id,
                    keeper_distribution=reg.packages[existing_pkg].distribution,
                    skipped_distribution=d.distribution,
                )
                continue
            reg._concept_by_id[c.id] = (d.import_name, c)

        for idiom in m.idioms:
            if idiom.id in reg._idiom_by_id:
                existing_pkg, _ = reg._idiom_by_id[idiom.id]
                _record_duplicate(
                    reg.errors,
                    kind_label="idiom id",
                    key=idiom.id,
                    keeper_distribution=reg.packages[existing_pkg].distribution,
                    skipped_distribution=d.distribution,
                )
                continue
            reg._idiom_by_id[idiom.id] = (d.import_name, idiom)

        for ap in m.anti_patterns:
            if ap.id in reg._anti_pattern_by_id:
                existing_pkg, _ = reg._anti_pattern_by_id[ap.id]
                _record_duplicate(
                    reg.errors,
                    kind_label="anti_pattern id",
                    key=ap.id,
                    keeper_distribution=reg.packages[existing_pkg].distribution,
                    skipped_distribution=d.distribution,
                )
                continue
            reg._anti_pattern_by_id[ap.id] = (d.import_name, ap)

    for dd in detector_successes:
        if dd.detector_id in reg.detectors:
            _record_duplicate(
                reg.errors,
                kind_label="detector id",
                key=dd.detector_id,
                keeper_distribution=reg.detectors[dd.detector_id].distribution,
                skipped_distribution=dd.distribution,
            )
            continue
        reg.detectors[dd.detector_id] = dd

    # Build extension reverse index in a second pass — needs full set of imports.
    for d in manifest_successes:
        if reg.packages.get(d.import_name) is not d:
            # This manifest was a duplicate and not registered; skip its extends.
            continue
        m = d.manifest
        for ext in m.extends:
            for provided in ext.provides:
                if provided.replaces_or_extends:
                    reg._extended_by[provided.replaces_or_extends].append(
                        f"{d.import_name}.{provided.name}"
                    )

    return reg
