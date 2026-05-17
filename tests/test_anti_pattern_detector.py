"""AST-based anti-pattern detection.

Tests cover both the success path (producer-registered detectors fire) and
the two error-surfacing paths:

1. ``detector_id`` set but no detector registered → loud RuntimeError
2. Registered detector raises during execution → error-severity match,
   not a swallowed exception.
"""

from __future__ import annotations

import ast
from typing import Any

import pytest

from biobabel._concept.anti_pattern_detector import detect_anti_patterns
from biobabel._registry.discovery import DiscoveredDetector
from biobabel.detector_api import DetectorMatch
from biobabel.manifest_api import AntiPatternDetection, AntiPatternSpec


def test_grob_in_loop_detected(registry):
    code = """
from grid_py import rect_grob, Unit, grid_draw
for i in range(50):
    grid_draw(rect_grob(x=Unit(i*0.01, "npc")))
"""
    hits = detect_anti_patterns(code, registry=registry, package="grid_py")
    assert any(h.anti_pattern_id == "grid_py.grob_in_loop" for h in hits)


def test_build_grobtree_passes(registry):
    code = """
from grid_py import rect_grob, Unit, grob_tree, grid_draw
rects = [rect_grob(x=Unit(i*0.01, "npc")) for i in range(50)]
grid_draw(grob_tree(*rects))
"""
    hits = detect_anti_patterns(code, registry=registry, package="grid_py")
    assert not any(h.anti_pattern_id == "grid_py.grob_in_loop" for h in hits)


def test_unbalanced_push_pop_detected(registry):
    code = """
from grid_py import push_viewport, pop_viewport, grid_rect
push_viewport(vp1)
push_viewport(vp2)
grid_rect()
pop_viewport()
# forgot the second pop
"""
    hits = detect_anti_patterns(code, registry=registry, package="grid_py")
    assert any(h.anti_pattern_id == "grid_py.unbalanced_push_pop" for h in hits)


def test_balanced_push_pop_passes(registry):
    code = """
push_viewport(vp1)
try:
    push_viewport(vp2)
    try:
        grid_rect()
    finally:
        pop_viewport()
finally:
    pop_viewport()
"""
    hits = detect_anti_patterns(code, registry=registry, package="grid_py")
    assert not any(h.anti_pattern_id == "grid_py.unbalanced_push_pop" for h in hits)


def test_unregistered_detector_id_raises_loudly(registry):
    """A producer that declares ``detector_id: rgrid.totally_made_up`` but
    does NOT ship a corresponding entry-point is a producer-config bug.
    The lint must fail loudly rather than silently skip, so the producer
    sees their mistake during testing."""
    bogus_spec = AntiPatternSpec(
        id="grid_py.bogus",
        name="bogus",
        detection=AntiPatternDetection(
            detector_id="rgrid.totally_made_up",
        ),
        why_bad="for tests",
    )
    registry._anti_pattern_by_id["grid_py.bogus"] = ("grid_py", bogus_spec)
    try:
        with pytest.raises(RuntimeError, match="no detector was registered"):
            detect_anti_patterns("x = 1\n", registry=registry, package="grid_py")
    finally:
        del registry._anti_pattern_by_id["grid_py.bogus"]


def test_detector_exception_surfaces_as_error_severity_match(registry):
    """A buggy detector must not break the whole lint. The exception is
    captured into an error-severity AntiPatternMatch so the LLM and logs
    both see it — careful try/except (catch with intent + immediate
    visibility), not the silent kind."""

    def _broken_detector(_tree: ast.AST, _args: dict[str, Any]) -> list[DetectorMatch]:
        raise ValueError("intentional test failure")

    registry.detectors["rgrid.broken"] = DiscoveredDetector(
        detector_id="rgrid.broken",
        distribution="rgrid-python",
        distribution_version="test",
        fn=_broken_detector,
    )
    broken_spec = AntiPatternSpec(
        id="grid_py.broken",
        name="broken detector",
        detection=AntiPatternDetection(detector_id="rgrid.broken"),
        why_bad="for tests",
    )
    registry._anti_pattern_by_id["grid_py.broken"] = ("grid_py", broken_spec)
    try:
        hits = detect_anti_patterns("x = 1\n", registry=registry, package="grid_py")
        broken_hits = [h for h in hits if h.anti_pattern_id == "grid_py.broken"]
        assert len(broken_hits) == 1
        h = broken_hits[0]
        assert h.severity == "error"
        assert "ValueError" in h.message
        assert "intentional test failure" in h.message
        assert "traceback" in h.detail
        # The rest of the lint must still have run — grob_in_loop / unbalanced
        # tests above demonstrate that even with one broken detector, others
        # still produce their normal matches (no broken-detector hits here
        # because the user code is trivial, but if it weren't, they would).
    finally:
        del registry.detectors["rgrid.broken"]
        del registry._anti_pattern_by_id["grid_py.broken"]


def test_regex_only_detection_still_works(registry):
    """Schema v2 only restructures the AST detection path; plain regex
    detection (used by most anti-patterns in Bio-Babel-public) is
    unchanged. Verify it still fires without any registered detector."""
    regex_spec = AntiPatternSpec(
        id="grid_py.regex_only",
        name="regex-only",
        detection=AntiPatternDetection(regex=r"forbidden_token"),
        why_bad="for tests",
    )
    registry._anti_pattern_by_id["grid_py.regex_only"] = ("grid_py", regex_spec)
    try:
        hits = detect_anti_patterns(
            "x = forbidden_token\n", registry=registry, package="grid_py"
        )
        assert any(h.anti_pattern_id == "grid_py.regex_only" for h in hits)
    finally:
        del registry._anti_pattern_by_id["grid_py.regex_only"]
