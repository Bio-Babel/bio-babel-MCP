"""Skill generator: per-package SKILL.md + biobabel-overview."""

from __future__ import annotations

import json
import re
from pathlib import Path

from biobabel._exporters.skills import build_skills

# Names that must never reappear in any generated or shipped skill surface:
# the consumer tools removed in the v0.3.0 surface trim, plus retired slash
# commands / sub-agents. The guard caught the latter but not the former, which
# is how three removed tools (health / match_failure / list_tools) lingered in
# the shipped plugin overviews — so they are pinned here too.
_REMOVED_SURFACE_MARKERS = (
    "biobabel.search_contracts",
    "biobabel.match_failure",
    "biobabel.health",
    "biobabel.list_tools",
    "biobabel.plan_workflow",
    "biobabel.check_prerequisites",
    "biobabel.list_traces",
    "biobabel.run_recipe",
    "biobabel.run_code",
    "/biobabel:migrate",
    "contract-retrofitter",
    "r-parity-auditor",
)

# Shipped overview SKILL.md bundles that must track the live MCP surface.
_SHIPPED_OVERVIEWS = (
    ("biobabel", "plugin/biobabel/skills/biobabel-overview/SKILL.md"),
    ("biobabel-codex", "plugin/biobabel-codex/skills/biobabel-overview/SKILL.md"),
)

# Shipped plugin manifests that advertise the tool count in their description.
_SHIPPED_MANIFESTS = (
    "plugin/biobabel/.claude-plugin/plugin.json",
    "plugin/biobabel-codex/.codex-plugin/plugin.json",
)


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
    assert "12 read-only MCP tools" in body
    for stale in _REMOVED_SURFACE_MARKERS:
        assert stale not in body, f"generated overview leaked removed surface: {stale}"


def test_shipped_plugin_overviews_match_current_surface():
    root = Path(__file__).resolve().parent.parent
    for bundle, rel in _SHIPPED_OVERVIEWS:
        body = (root / rel).read_text()
        assert "12 read-only MCP tools" in body, f"{bundle}: stale tool count"
        for stale in _REMOVED_SURFACE_MARKERS:
            assert stale not in body, f"{bundle}: leaked removed surface: {stale}"


def test_shipped_plugin_manifests_match_current_surface():
    root = Path(__file__).resolve().parent.parent
    for rel in _SHIPPED_MANIFESTS:
        description = json.loads((root / rel).read_text())["description"]
        assert "12 read-only MCP tools" in description, f"{rel}: stale tool count"
        assert "run complete code" not in description
        assert "slash commands" not in description
        assert "23 MCP tools" not in description


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
