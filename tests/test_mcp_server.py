"""MCP server: tool wiring + envelope contract."""

from __future__ import annotations

from biobabel._runtime.session import SessionStore
from biobabel.mcp.server import BiobabelMCPServer


def test_server_wires_22_tools(registry):
    server = BiobabelMCPServer(registry=registry, sessions=SessionStore())
    assert server.tool_count == 22


def test_list_packages_envelope_surfaces_ranking_signals(registry):
    """list_packages must surface every signal the LLM needs to rank
    packages itself — biobabel deliberately does not score."""
    server = BiobabelMCPServer(registry=registry, sessions=SessionStore())
    env = server.call("biobabel.list_packages")
    assert env["ok"] is True
    assert env["tool_name"] == "biobabel.list_packages"
    packages = env["outputs"]["packages"]
    assert {p["import_name"] for p in packages} >= {"grid_py", "monocle3_py"}
    sample = packages[0]
    for field in ("triggers", "task_tags", "capabilities", "domain_tags", "not_when", "foundation"):
        assert field in sample, f"list_packages must expose '{field}' for LLM ranking"


def test_describe_concept(registry):
    server = BiobabelMCPServer(registry=registry, sessions=SessionStore())
    env = server.call("biobabel.describe_concept", concept_id="grid_py.Viewport")
    assert env["ok"]
    assert env["outputs"]["package"] == "grid_py"
    assert env["outputs"]["concept"]["name"] == "Viewport"


def test_check_code_flags_anti_pattern(registry):
    server = BiobabelMCPServer(registry=registry, sessions=SessionStore())
    code = """
from grid_py import rect_grob, Unit, grid_draw
for i in range(10):
    grid_draw(rect_grob(x=Unit(i*0.1, "npc")))
"""
    env = server.call("biobabel.check_code", code=code, package="grid_py")
    assert env["ok"]
    issues = env["outputs"]["issues"]
    assert any(i.get("anti_pattern_id") == "grid_py.grob_in_loop" for i in issues)


def test_unknown_tool_returns_error_envelope(registry):
    server = BiobabelMCPServer(registry=registry, sessions=SessionStore())
    env = server.call("biobabel.no_such_tool")
    assert env["ok"] is False
    assert env["error_code"] == "unknown_tool"


def test_recommend_tool_is_absent(registry):
    """biobabel.recommend was removed: LLM ranks packages itself from
    list_packages signals. No hand-tuned scoring inside biobabel."""
    server = BiobabelMCPServer(registry=registry, sessions=SessionStore())
    assert "biobabel.recommend" not in server.tool_names
    env = server.call("biobabel.recommend", task="anything")
    assert env["ok"] is False
    assert env["error_code"] == "unknown_tool"


def test_list_tools_returns_all(registry):
    server = BiobabelMCPServer(registry=registry, sessions=SessionStore())
    env = server.call("biobabel.list_tools")
    assert env["ok"]
    assert len(env["outputs"]["tools"]) == 22


def test_removed_tools_are_absent(registry):
    """These tools were removed during scope reduction; assert they're gone."""
    server = BiobabelMCPServer(registry=registry, sessions=SessionStore())
    for removed in (
        "biobabel.r_translate",
        "biobabel.r_verify",
        "biobabel.migrate",
        "biobabel.new_contract",  # CLI-only now
        "biobabel.scaffold",
    ):
        assert removed not in server.tool_names, f"{removed} should not be in MCP surface"


def test_health(registry):
    server = BiobabelMCPServer(registry=registry, sessions=SessionStore())
    env = server.call("biobabel.health")
    assert env["ok"]
    assert env["outputs"]["packages"] >= 2
