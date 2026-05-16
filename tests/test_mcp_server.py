"""MCP server: tool wiring + envelope contract."""

from __future__ import annotations

from biobabel._runtime.session import SessionStore
from biobabel.mcp.server import BiobabelMCPServer


def test_server_wires_23_tools(registry):
    server = BiobabelMCPServer(registry=registry, sessions=SessionStore())
    assert server.tool_count == 23


def test_list_packages_envelope(registry):
    server = BiobabelMCPServer(registry=registry, sessions=SessionStore())
    env = server.call("biobabel.list_packages")
    assert env["ok"] is True
    assert env["tool_name"] == "biobabel.list_packages"
    assert "packages" in env["outputs"]
    assert {p["import_name"] for p in env["outputs"]["packages"]} >= {"grid_py", "monocle3_py"}


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


def test_recommend_envelope(registry):
    server = BiobabelMCPServer(registry=registry, sessions=SessionStore())
    env = server.call("biobabel.recommend", task="pseudotime trajectory", k=3)
    assert env["ok"]
    recs = env["outputs"]["recommendations"]
    assert recs and recs[0]["package"] == "monocle3_py"


def test_list_tools_returns_all(registry):
    server = BiobabelMCPServer(registry=registry, sessions=SessionStore())
    env = server.call("biobabel.list_tools")
    assert env["ok"]
    assert len(env["outputs"]["tools"]) == 23


def test_removed_tools_are_absent(registry):
    """The scope reduction (ADR-0005) removed these 4 tools. Assert they're gone."""
    server = BiobabelMCPServer(registry=registry, sessions=SessionStore())
    for removed in (
        "biobabel.r_translate",
        "biobabel.r_verify",
        "biobabel.migrate",
        "biobabel.new_contract",  # CLI-only now
        "biobabel.scaffold",       # removed earlier (ADR-0004)
    ):
        assert removed not in server.tool_names, f"{removed} should not be in MCP surface"


def test_health(registry):
    server = BiobabelMCPServer(registry=registry, sessions=SessionStore())
    env = server.call("biobabel.health")
    assert env["ok"]
    assert env["outputs"]["packages"] >= 2
