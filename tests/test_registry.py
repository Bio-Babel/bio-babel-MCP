"""Registry: discovery + lookups + provenance hash."""

from __future__ import annotations

from biobabel._registry.sha import manifest_sha256


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
