"""Stdio transport: end-to-end progress notification wiring.

Exercises the path that P2-3 added: when ``tools/call`` arrives with
``params._meta.progressToken``, the transport must emit one
``notifications/progress`` JSON-RPC message per chunk the streaming tool
produces, and only then send the final ``tools/call`` result.
"""

from __future__ import annotations

import io
import json
import sys

import pytest

from biobabel._runtime.session import SessionStore
from biobabel.mcp.server import BiobabelMCPServer
from biobabel.mcp.transports.stdio import StdioTransport

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="rlimits POSIX-only")


def _drive(server: BiobabelMCPServer, *requests: dict) -> list[dict]:
    """Feed *requests* to a StdioTransport and return parsed responses."""
    in_buf = io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n")
    out_buf = io.StringIO()
    transport = StdioTransport(server, stdin=in_buf, stdout=out_buf)
    transport.serve_forever()
    return [json.loads(line) for line in out_buf.getvalue().splitlines() if line]


def test_tools_call_without_progress_token_emits_no_notifications(registry, tmp_path):
    """Default behaviour: no progressToken → no progress notifications.
    The only emitted message is the tools/call result."""
    store = SessionStore(root=tmp_path / "sessions")
    server = BiobabelMCPServer(registry=registry, sessions=store)
    responses = _drive(server, {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "biobabel.run_code",
            "arguments": {"code": "print('hi')"},
        },
    })
    assert len(responses) == 1
    assert responses[0]["id"] == 7
    assert "result" in responses[0]


def test_tools_call_with_progress_token_emits_notifications_first(registry, tmp_path):
    """With ``_meta.progressToken``, the transport must emit one
    ``notifications/progress`` per chunk BEFORE the final result. Each
    notification's ``message`` is a JSON-encoded payload that recovers
    the stream + text losslessly."""
    store = SessionStore(root=tmp_path / "sessions")
    server = BiobabelMCPServer(registry=registry, sessions=store)
    responses = _drive(server, {
        "jsonrpc": "2.0",
        "id": "req-1",
        "method": "tools/call",
        "params": {
            "name": "biobabel.run_code",
            "arguments": {"code": "print('alpha')\nprint('beta')"},
            "_meta": {"progressToken": "tok-42"},
        },
    })

    notifications = [r for r in responses if r.get("method") == "notifications/progress"]
    results = [r for r in responses if "result" in r]
    assert len(results) == 1, results
    assert len(notifications) >= 1, notifications

    # Every progress notification carries the right token and a monotone counter.
    progress_seq = [n["params"]["progress"] for n in notifications]
    assert progress_seq == sorted(progress_seq)
    assert all(n["params"]["progressToken"] == "tok-42" for n in notifications)

    # Stream payloads decode losslessly.
    decoded = [json.loads(n["params"]["message"]) for n in notifications]
    assert all(d["stream"] in {"stdout", "stderr"} for d in decoded)
    combined = "".join(d["text"] for d in decoded)
    assert "alpha" in combined
    assert "beta" in combined

    # Order: every notification comes BEFORE the result (read-out order is
    # write order, since both buffers are the same StringIO).
    first_result_idx = next(i for i, r in enumerate(responses) if "result" in r)
    assert all(i < first_result_idx for i, r in enumerate(responses)
               if r.get("method") == "notifications/progress")


def test_progress_token_routes_correctly_when_present_on_non_streaming_tool(
    registry, tmp_path
):
    """A non-streaming tool (e.g. list_packages) with a progressToken in
    the request is fine — no notifications emitted, single result."""
    store = SessionStore(root=tmp_path / "sessions")
    server = BiobabelMCPServer(registry=registry, sessions=store)
    responses = _drive(server, {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "biobabel.list_packages",
            "arguments": {},
            "_meta": {"progressToken": "tok-1"},
        },
    })
    notifications = [r for r in responses if r.get("method") == "notifications/progress"]
    assert notifications == []
    assert len([r for r in responses if "result" in r]) == 1
