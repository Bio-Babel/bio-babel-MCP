"""Skill generator: per-package SKILL.md + biobabel-overview."""

from __future__ import annotations

import re
from pathlib import Path

from biobabel._exporters.skills import build_skills


def test_build_skills_writes_overview_even_with_empty_registry(tmp_path, registry):
    # Use the fixture registry from conftest.py
    out = tmp_path / "skills"
    result = build_skills(registry, out)
    # The overview is always written
    overview = out / "biobabel-overview" / "SKILL.md"
    assert overview.is_file()
    assert "biobabel-overview" in overview.read_text()
    assert overview in result.written


def test_overview_lists_packages_by_class(tmp_path, registry):
    out = tmp_path / "skills"
    build_skills(registry, out)
    body = (out / "biobabel-overview" / "SKILL.md").read_text()
    assert "Class analysis" in body
    assert "Class grammar" in body
    assert "monocle3_py" in body
    assert "grid_py" in body


def test_overview_frontmatter_has_biobabel_version(tmp_path, registry):
    out = tmp_path / "skills"
    build_skills(registry, out)
    body = (out / "biobabel-overview" / "SKILL.md").read_text()
    front = re.search(r"\A---\n(.*?)\n---\n", body, re.DOTALL)
    assert front is not None
    assert "biobabel_version:" in front.group(1)


def test_overview_reflects_current_mcp_surface(tmp_path, registry):
    """The generated overview must not drift back to removed consumer tools."""
    out = tmp_path / "skills"
    build_skills(registry, out)
    body = (out / "biobabel-overview" / "SKILL.md").read_text()
    assert "20 MCP tools" in body
    for stale in (
        "biobabel.r_translate",
        "/biobabel:r-translate",
        "/biobabel:migrate",
        "contract-retrofitter",
        "r-parity-auditor",
    ):
        assert stale not in body


def test_shipped_plugin_overview_matches_current_surface():
    root = Path(__file__).resolve().parent.parent
    body = (root / "plugin" / "biobabel" / "skills" / "biobabel-overview" / "SKILL.md").read_text()
    assert "20 MCP tools" in body
    for stale in (
        "biobabel.r_translate",
        "/biobabel:r-translate",
        "/biobabel:migrate",
        "contract-retrofitter",
        "r-parity-auditor",
    ):
        assert stale not in body


def test_packages_without_skill_md_are_skipped_with_reason(tmp_path, registry):
    """Fixture's 'monocle3_py' is fictitious (not pip-installed); must be skipped.

    grid_py may or may not be installed in this test env. If it is and ships a
    real _biobabel/skill.md, it gets written; if not, it's skipped. The
    invariant we care about is that *fictitious* packages always skip with a
    clear reason, never crash.
    """
    out = tmp_path / "skills"
    result = build_skills(registry, out)
    skipped_names = {pkg for pkg, _ in result.skipped}
    assert "monocle3_py" in skipped_names
    for _, reason in result.skipped:
        assert "skill.md" in reason
