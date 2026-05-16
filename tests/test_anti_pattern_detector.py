"""AST-based anti-pattern detection."""

from __future__ import annotations

from biobabel._concept.anti_pattern_detector import detect_anti_patterns


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
