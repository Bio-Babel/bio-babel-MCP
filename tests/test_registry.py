"""Registry / lockfile / differ."""

from __future__ import annotations

from biobabel._registry.differ import diff_registries
from biobabel._registry.lockfile import build_lock, manifest_sha256


def test_lock_stable_under_unchanged_manifest(registry):
    lock1 = build_lock(registry)
    lock2 = build_lock(registry)
    assert [e.manifest_sha256 for e in lock1.entries] == [e.manifest_sha256 for e in lock2.entries]


def test_lock_changes_when_manifest_changes(registry, grammar_manifest):
    lock1 = build_lock(registry)
    grammar_manifest.maturity = "stable"
    registry._anti_pattern_by_id  # force registry coherence
    # mutate via re-discovery surrogate
    sha_before = lock1.entries[0].manifest_sha256
    registry.packages["grid_py"].manifest.maturity = "stable"  # type: ignore[misc]
    sha_after = manifest_sha256(registry.packages["grid_py"].manifest)
    assert sha_before != sha_after


def test_differ_detects_added_removed_changed(registry):
    lock_old = build_lock(registry)
    # remove monocle3_py to simulate uninstall
    monocle = registry.packages.pop("monocle3_py")
    lock_new = build_lock(registry)
    diff = diff_registries(lock_old, lock_new)
    assert "monocle3_py" in diff.removed
    registry.packages["monocle3_py"] = monocle


def test_lookups(registry):
    assert registry.manifest("grid_py") is not None
    assert registry.concept("grid_py.Viewport") is not None
    assert registry.idiom("grid_py.push_draw_pop") is not None
    assert registry.function("monocle3.preprocess_cds") is not None
    assert registry.workflow("monocle3.basic_trajectory") is not None
