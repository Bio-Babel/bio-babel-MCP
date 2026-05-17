"""Registry: discovery + lookups + provenance hash."""

from __future__ import annotations

from unittest.mock import patch

from biobabel._registry.builder import build_registry
from biobabel._registry.discovery import (
    DiscoveredDetector,
    DiscoveredManifest,
)
from biobabel._registry.sha import manifest_sha256
from biobabel.manifest_api import (
    ConceptSpec,
    FunctionContract,
    MentalModel,
    PackageManifest,
)


def test_manifest_sha256_is_stable_for_unchanged_manifest(registry):
    """The hash function used to stamp generated SKILL.md files must be
    deterministic for the same manifest content.
    """
    m = registry.packages["grid_py"].manifest
    assert manifest_sha256(m) == manifest_sha256(m)


def test_manifest_sha256_changes_when_manifest_changes(registry):
    m = registry.packages["grid_py"].manifest
    before = manifest_sha256(m)
    m.maturity = "stable"  # type: ignore[misc]
    after = manifest_sha256(m)
    assert before != after


def test_lookups(registry):
    assert registry.manifest("grid_py") is not None
    assert registry.concept("grid_py.Viewport") is not None
    assert registry.idiom("grid_py.push_draw_pop") is not None
    assert registry.function("monocle3.preprocess_cds") is not None
    assert registry.workflow("monocle3.basic_trajectory") is not None


# --- collision detection ---------------------------------------------------
#
# Two distributions registering the same identifier must not silently
# last-write-wins. ``build_registry`` records each collision as a
# ``DiscoveryError(kind="duplicate")`` so ``biobabel.health`` can surface it.


def _mk_pkg(import_name: str, *, distribution: str, concepts=(), functions=()) -> DiscoveredManifest:
    return DiscoveredManifest(
        import_name=import_name,
        distribution=distribution,
        distribution_version="1.0.0",
        manifest=PackageManifest(
            repo="x",
            distribution=distribution,
            import_name=import_name,
            display_name=import_name,
            contract_class="analysis" if functions else "grammar",
            concepts=list(concepts),
            functions=list(functions),
        ),
    )


def _build_with(manifests, detectors=()):
    with (
        patch("biobabel._registry.builder.discover",
              return_value=(list(manifests), [])),
        patch("biobabel._registry.builder.discover_detectors",
              return_value=(list(detectors), [])),
    ):
        return build_registry()


def test_duplicate_package_import_name_is_recorded_first_wins():
    pkg_a = _mk_pkg("grid_py", distribution="rgrid-python")
    pkg_b = _mk_pkg("grid_py", distribution="rgrid-python-fork")

    reg = _build_with([pkg_a, pkg_b])

    # First wins
    assert reg.packages["grid_py"].distribution == "rgrid-python"
    # Collision recorded loud
    dups = [e for e in reg.errors if e.kind == "duplicate"]
    assert len(dups) == 1
    assert dups[0].name == "grid_py"
    assert dups[0].distribution == "rgrid-python-fork"
    assert "package import_name" in dups[0].error


def test_duplicate_function_id_across_packages_is_recorded():
    fn = FunctionContract(
        id="shared.fn",
        import_path="shared.fn",
        execution_class="stateless",
    )
    pkg_a = _mk_pkg("pkg_a", distribution="dist-a", functions=[fn])
    pkg_b = _mk_pkg("pkg_b", distribution="dist-b", functions=[fn])

    reg = _build_with([pkg_a, pkg_b])

    # Both packages registered (different import_names) — no package collision
    assert "pkg_a" in reg.packages and "pkg_b" in reg.packages
    # First function wins
    assert reg.function("shared.fn")[0] == "pkg_a"
    # Collision recorded
    dups = [e for e in reg.errors if e.kind == "duplicate" and "function id" in e.error]
    assert len(dups) == 1
    assert dups[0].name == "shared.fn"


def test_duplicate_concept_id_across_packages_is_recorded():
    """The old P3-4 scenario: two packages declaring the same concept id
    without namespacing. Catches lazy producers who skip the
    ``pkg.ConceptName`` convention."""
    c = ConceptSpec(
        id="Viewport",
        name="Viewport",
        category="x",
        description="",
        mental_model=MentalModel(general=""),
    )
    pkg_a = _mk_pkg("pkg_a", distribution="dist-a", concepts=[c])
    pkg_b = _mk_pkg("pkg_b", distribution="dist-b", concepts=[c])

    reg = _build_with([pkg_a, pkg_b])

    assert reg.concept("Viewport")[0] == "pkg_a"
    dups = [e for e in reg.errors if e.kind == "duplicate" and "concept id" in e.error]
    assert len(dups) == 1


def test_duplicate_detector_id_is_recorded():
    def _fake_detector(tree, args):
        return []

    det_a = DiscoveredDetector(
        detector_id="rgrid.for_loop_calls",
        distribution="rgrid-python",
        distribution_version="1.0",
        fn=_fake_detector,
    )
    det_b = DiscoveredDetector(
        detector_id="rgrid.for_loop_calls",
        distribution="rgrid-python-fork",
        distribution_version="1.0",
        fn=_fake_detector,
    )

    reg = _build_with([], detectors=[det_a, det_b])

    assert reg.detectors["rgrid.for_loop_calls"].distribution == "rgrid-python"
    dups = [e for e in reg.errors if e.kind == "duplicate" and "detector id" in e.error]
    assert len(dups) == 1


def test_duplicate_package_skips_remaining_member_registrations():
    """When a package's import_name collides, the rest of its manifest
    members are NOT registered either — otherwise a forked package could
    quietly inject functions/concepts/idioms under the keeper's name."""
    fn = FunctionContract(
        id="grid_py.fn",
        import_path="grid_py.fn",
        execution_class="stateless",
    )
    keeper = _mk_pkg("grid_py", distribution="rgrid-python")
    forked = _mk_pkg("grid_py", distribution="rgrid-python-fork", functions=[fn])

    reg = _build_with([keeper, forked])

    # forked.fn must NOT be in the registry (fork was rejected wholesale)
    assert reg.function("grid_py.fn") is None
    # The package import_name collision is the only recorded duplicate;
    # no spurious function-id collision is emitted because the fork's
    # function was never attempted.
    dups = [e for e in reg.errors if e.kind == "duplicate"]
    assert len(dups) == 1
    assert "package import_name" in dups[0].error
