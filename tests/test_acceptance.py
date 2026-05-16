"""Acceptance criteria tests that exercise the full pipe.

Skipped in environments where the upstream Bio-Babel packages aren't
installed. On a CI runner with `scales-python`, `gtable-python`,
`rgrid-python`, `monocle3-python`, `ggplot2-python` installed, every test
here must pass.
"""

from __future__ import annotations

import importlib.util

import pytest

from biobabel._registry.builder import build_registry
from biobabel.mcp.server import build_server


def _pkg_installed(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


needs_ggplot2 = pytest.mark.skipif(
    not _pkg_installed("ggplot2_py"),
    reason="acceptance test needs ggplot2-python installed with its _biobabel/ contract",
)
needs_monocle3 = pytest.mark.skipif(
    not _pkg_installed("monocle3"),
    reason="acceptance test needs monocle3-python installed",
)
needs_grid_py = pytest.mark.skipif(
    not _pkg_installed("grid_py"),
    reason="acceptance test needs rgrid-python installed",
)


@needs_ggplot2
def test_ac_ggplot2_describe_aes_includes_keyword_warning():
    """ggplot2's `aes` symbol must surface the Python kwarg/string requirement
    (this is the canonical bug LLM agents hit when porting R ggplot calls)."""
    server = build_server()
    env = server.call("biobabel.describe_symbol", symbol_id="ggplot2_py.aes")
    assert env["ok"], env
    fn = env["outputs"]["function"]
    # The Python aes must signal: keyword-only + string column names
    fix_text = " ".join(f["suggest"][0] for f in fn["failure_fixes"])
    assert "keyword" in fix_text.lower() or "string" in fix_text.lower()


@needs_monocle3
def test_ac4_monocle3_describe_symbol_full_contract():
    """AC #4: describe_symbol('monocle3.preprocess_cds') returns full state-graph contract."""
    server = build_server()
    env = server.call("biobabel.describe_symbol", symbol_id="monocle3.preprocess_cds")
    assert env["ok"], env
    fn = env["outputs"]["function"]
    assert fn["execution_class"] == "adata_mutation"
    assert "Size_Factor" in str(fn["requires"])
    assert "X_pca" in str(fn["writes"])
    assert "monocle3.reduce_dimension" in fn["next"]


@needs_monocle3
def test_ac_plan_workflow_pseudotime():
    """plan_workflow('pseudotime trajectory') resolves to monocle3.basic_trajectory with 6 steps."""
    server = build_server()
    env = server.call("biobabel.plan_workflow", task="pseudotime trajectory")
    assert env["ok"], env
    assert env["outputs"]["source"] == "workflow_contract"
    assert env["outputs"]["workflow_id"] == "monocle3.basic_trajectory"
    assert len(env["outputs"]["steps"]) == 6


@needs_ggplot2
def test_ggplot2_constant_inside_aes_is_flagged():
    """Anti-pattern detector catches color='red' inside aes() — the cardinal ggplot bug."""
    server = build_server()
    code = """
from ggplot2_py import ggplot, aes, geom_point
from ggplot2_py.datasets import mpg
p = ggplot(mpg, aes(x="displ", y="hwy")) + geom_point(aes(color="red"))
"""
    env = server.call("biobabel.check_code", code=code, package="ggplot2_py")
    ids = [i.get("anti_pattern_id") for i in env["outputs"]["issues"]]
    assert "ggplot2_py.constant_inside_aes" in ids


@needs_grid_py
def test_grid_py_grob_in_loop_is_flagged():
    """Anti-pattern detector catches grid_draw() in a for-loop."""
    server = build_server()
    code = """
from grid_py import rect_grob, Unit, grid_draw
for i in range(10):
    grid_draw(rect_grob(x=Unit(i*0.1, "npc")))
"""
    env = server.call("biobabel.check_code", code=code, package="grid_py")
    ids = [i.get("anti_pattern_id") for i in env["outputs"]["issues"]]
    assert "grid_py.grob_in_loop" in ids


def test_registry_has_all_5_onboarded_packages():
    """When all 5 currently-onboarded Bio-Babel packages are installed, biobabel sees them."""
    if not all(_pkg_installed(n) for n in ("scales", "grid_py", "gtable_py", "monocle3", "ggplot2_py")):
        pytest.skip("requires all 5 packages installed")
    reg = build_registry()
    names = {d.import_name for d in reg.list_packages()}
    assert {"scales", "grid_py", "gtable_py", "monocle3", "ggplot2_py"} <= names
    assert not reg.errors, f"unexpected discovery errors: {reg.errors}"
