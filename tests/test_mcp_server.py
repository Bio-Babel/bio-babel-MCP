"""MCP server: tool wiring + envelope contract."""

from __future__ import annotations

from biobabel._runtime.session import SessionStore
from biobabel.mcp.server import BiobabelMCPServer


def test_server_wires_20_tools(registry):
    """Surface is now 20 — was 22 before the P2-2 + P2-3 bundle trimmed
    ``create_session`` and ``list_handles`` (sessions became server-side
    plumbing; active handles ride in every runtime tool's response)."""
    server = BiobabelMCPServer(registry=registry, sessions=SessionStore())
    assert server.tool_count == 20


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
    assert len(env["outputs"]["tools"]) == 20


def test_removed_tools_are_absent(registry):
    """These tools were removed during scope reduction; assert they're gone.

    Order of removal:
    - early: r_translate, r_verify, migrate, scaffold, new_contract (CLI now)
    - P2-2 + P2-3 bundle (2026-05-17): create_session, list_handles
    """
    server = BiobabelMCPServer(registry=registry, sessions=SessionStore())
    for removed in (
        "biobabel.r_translate",
        "biobabel.r_verify",
        "biobabel.migrate",
        "biobabel.new_contract",
        "biobabel.scaffold",
        "biobabel.create_session",
        "biobabel.list_handles",
    ):
        assert removed not in server.tool_names, f"{removed} should not be in MCP surface"


def test_health(registry):
    server = BiobabelMCPServer(registry=registry, sessions=SessionStore())
    env = server.call("biobabel.health")
    assert env["ok"]
    assert env["outputs"]["packages"] >= 2


# --- P2-2 trim + P2-3 streaming integration -------------------------------


def test_run_code_without_session_id_uses_default(registry, tmp_path):
    store = SessionStore(root=tmp_path / "sessions")
    server = BiobabelMCPServer(registry=registry, sessions=store)
    env = server.call("biobabel.run_code", code="print('hi')")
    assert env["ok"], env
    assert "session_id" in env["outputs"]
    sid = env["outputs"]["session_id"]
    assert sid in store.list_sessions()

    # Re-calling without session_id reuses the same default session.
    env2 = server.call("biobabel.run_code", code="print('again')")
    assert env2["outputs"]["session_id"] == sid
    assert len(store.list_sessions()) == 1


def test_run_code_response_includes_active_handles(registry, tmp_path):
    store = SessionStore(root=tmp_path / "sessions")
    server = BiobabelMCPServer(registry=registry, sessions=store)
    env = server.call(
        "biobabel.run_code",
        code="from pathlib import Path\nPath('out.txt').write_text('hi')",
    )
    assert env["ok"], env
    handles = env["outputs"]["active_handles"]
    # A new artifact was produced → it shows up in active_handles.artifacts.
    assert len(handles["artifacts"]) == 1


def test_explicit_unknown_session_id_is_loud_error(registry, tmp_path):
    """Passing a session_id that doesn't exist is a deliberate signal —
    fail loud rather than silently routing to the default."""
    store = SessionStore(root=tmp_path / "sessions")
    server = BiobabelMCPServer(registry=registry, sessions=store)
    env = server.call(
        "biobabel.run_code", code="print('hi')", session_id="no_such_session"
    )
    assert not env["ok"]
    assert env["error_code"] == "session_not_found"


def test_server_call_forwards_progress_to_streaming_tool(registry, tmp_path):
    store = SessionStore(root=tmp_path / "sessions")
    server = BiobabelMCPServer(registry=registry, sessions=store)

    received: list[dict] = []
    server.call(
        "biobabel.run_code",
        progress=received.append,
        code="print('chunk1')\nprint('chunk2')",
    )
    # ``run_code`` is in the ``streams=True`` set → progress must fire.
    texts = "".join(p.get("text", "") for p in received)
    assert "chunk1" in texts
    assert "chunk2" in texts
    # Payload shape contract: each event has 'stream' ∈ {stdout, stderr}.
    assert all(p.get("stream") in {"stdout", "stderr"} for p in received)


def test_server_call_does_not_forward_progress_to_non_runtime_tool(registry, tmp_path):
    """Discovery / planning / concept / validation / meta handlers don't
    accept ``progress`` — they ignore it even when passed."""
    store = SessionStore(root=tmp_path / "sessions")
    server = BiobabelMCPServer(registry=registry, sessions=store)
    received: list[dict] = []
    env = server.call("biobabel.list_packages", progress=received.append)
    assert env["ok"]
    assert received == []


def test_health_outputs_include_handles_by_session(registry, tmp_path):
    store = SessionStore(root=tmp_path / "sessions")
    server = BiobabelMCPServer(registry=registry, sessions=store)
    server.call("biobabel.run_code", code="print('hi')")  # creates the default session
    env = server.call("biobabel.health")
    assert env["ok"]
    assert env["outputs"]["sessions"] == 1
    handles_by_session = env["outputs"]["handles_by_session"]
    assert len(handles_by_session) == 1
    only_session = next(iter(handles_by_session.values()))
    # Empty handles map shape (no artifacts since `print('hi')` writes no files).
    for slot in ("adata", "dataframes", "plots", "artifacts"):
        assert slot in only_session


def test_list_traces_without_runtime_does_not_create_default_session(registry, tmp_path):
    store = SessionStore(root=tmp_path / "sessions")
    server = BiobabelMCPServer(registry=registry, sessions=store)
    env = server.call("biobabel.list_traces")
    assert env["ok"]
    assert env["outputs"] == {"session_id": None, "traces": []}
    assert store.list_sessions() == []


def test_runtime_success_records_trace_in_default_session(registry, tmp_path):
    store = SessionStore(root=tmp_path / "sessions")
    server = BiobabelMCPServer(registry=registry, sessions=store)
    code = "from pathlib import Path\nPath('trace_artifact.txt').write_text('payload')"

    run_env = server.call("biobabel.run_code", code=code)
    assert run_env["ok"], run_env
    artifact_id = run_env["outputs"]["new_artifacts"][0]["artifact_id"]

    traces_env = server.call("biobabel.list_traces")
    traces = traces_env["outputs"]["traces"]
    assert traces_env["outputs"]["session_id"] == run_env["outputs"]["session_id"]
    assert len(traces) == 1
    trace = traces[0]
    assert trace["tool_name"] == "biobabel.run_code"
    assert trace["ok"] is True
    assert trace["error_code"] == ""
    assert trace["handle_refs_in"] == []
    assert trace["handle_refs_out"] == [artifact_id]
    assert trace["args_summary"]["code_hash"] == run_env["outputs"]["code_hash"]
    assert "session_id" not in trace  # already at outputs top level
    assert "write_text" not in str(trace)
    assert "payload" not in str(trace)


def test_load_dataframe_trace_records_output_handle_and_path_summary(registry, tmp_path):
    csv_path = tmp_path / "input.csv"
    csv_path.write_text("a,b\n1,2\n", encoding="utf-8")
    store = SessionStore(root=tmp_path / "sessions")
    server = BiobabelMCPServer(registry=registry, sessions=store)

    load_env = server.call("biobabel.load_dataframe", path=str(csv_path))
    assert load_env["ok"], load_env
    trace = server.call("biobabel.list_traces")["outputs"]["traces"][0]
    assert trace["tool_name"] == "biobabel.load_dataframe"
    assert trace["handle_refs_out"] == [load_env["outputs"]["df_id"]]
    assert trace["args_summary"]["path_name"] == "input.csv"
    assert trace["args_summary"]["path_suffix"] == ".csv"
    assert str(tmp_path) not in str(trace)


def test_get_artifact_trace_records_artifact_as_input_ref(registry, tmp_path):
    store = SessionStore(root=tmp_path / "sessions")
    server = BiobabelMCPServer(registry=registry, sessions=store)
    run_env = server.call(
        "biobabel.run_code",
        code="from pathlib import Path\nPath('artifact.txt').write_text('payload')",
    )
    artifact_id = run_env["outputs"]["new_artifacts"][0]["artifact_id"]

    artifact_env = server.call("biobabel.get_artifact", artifact_id=artifact_id)
    assert artifact_env["ok"], artifact_env
    trace = server.call("biobabel.list_traces")["outputs"]["traces"][0]
    assert trace["tool_name"] == "biobabel.get_artifact"
    assert trace["handle_refs_in"] == [artifact_id]
    assert trace["handle_refs_out"] == []


def test_runtime_error_records_trace_without_raw_code(registry, tmp_path):
    store = SessionStore(root=tmp_path / "sessions")
    server = BiobabelMCPServer(registry=registry, sessions=store)
    code = "import subprocess\nprint('should not run')"

    run_env = server.call("biobabel.run_code", code=code)
    assert not run_env["ok"]
    assert run_env["error_code"] == "security_violation"

    traces = server.call("biobabel.list_traces")["outputs"]["traces"]
    assert len(traces) == 1
    trace = traces[0]
    assert trace["tool_name"] == "biobabel.run_code"
    assert trace["ok"] is False
    assert trace["error_code"] == "security_violation"
    assert trace["args_summary"]["code_hash"] == run_env["details"]["code_hash"]
    assert trace["args_summary"]["result"]["stderr_len"] > 0
    assert "subprocess" not in str(trace)
    assert "should not run" not in str(trace)


def test_non_runtime_tools_do_not_record_traces(registry, tmp_path):
    store = SessionStore(root=tmp_path / "sessions")
    server = BiobabelMCPServer(registry=registry, sessions=store)
    server.call("biobabel.run_code", code="print('hi')")
    server.call("biobabel.list_packages")
    server.call("biobabel.check_code", code="print('hi')")
    traces = server.call("biobabel.list_traces")["outputs"]["traces"]
    assert [t["tool_name"] for t in traces] == ["biobabel.run_code"]


def test_list_traces_accepts_explicit_session_id(registry, tmp_path):
    store = SessionStore(root=tmp_path / "sessions")
    server = BiobabelMCPServer(registry=registry, sessions=store)
    run_env = server.call("biobabel.run_code", code="print('hi')")
    sid = run_env["outputs"]["session_id"]

    traces_env = server.call("biobabel.list_traces", session_id=sid)
    assert traces_env["ok"]
    assert traces_env["outputs"]["session_id"] == sid
    assert len(traces_env["outputs"]["traces"]) == 1


def test_runtime_tool_count_is_six(registry):
    """Group 5 (Runtime) shrank 8 → 6: create_session + list_handles removed."""
    server = BiobabelMCPServer(registry=registry, sessions=SessionStore())
    runtime_tools = [name for name in server.tool_names if server.tool(name).group == "runtime"]
    assert len(runtime_tools) == 6, runtime_tools
    expected = {
        "biobabel.load_adata",
        "biobabel.load_dataframe",
        "biobabel.run_code",
        "biobabel.run_recipe",
        "biobabel.inspect_object",
        "biobabel.get_artifact",
    }
    assert set(runtime_tools) == expected


def test_streaming_marker_is_set_only_on_run_code_and_run_recipe(registry):
    server = BiobabelMCPServer(registry=registry, sessions=SessionStore())
    streaming = {name for name in server.tool_names if server.tool(name).streams}
    assert streaming == {"biobabel.run_code", "biobabel.run_recipe"}
