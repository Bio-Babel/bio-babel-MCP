"""Stdio JSON-RPC 2.0 transport, MCP-compatible at the wire level.

We deliberately avoid hard-binding to a specific MCP SDK so that:

  * Smoke tests can drive the server without external deps.
  * Users can wire any MCP client (Claude Code, Cursor, Continue, ...) that
    speaks the standard `initialize`/`tools/list`/`tools/call` protocol.

Progress notifications
----------------------
When a client sends ``tools/call`` with a ``params._meta.progressToken``
(per MCP spec), this transport constructs a per-call emitter that
forwards each partial payload as a ``notifications/progress`` JSON-RPC
notification. Streaming-enabled tools (``run_code``, ``run_recipe``) use
this to ship stdout/stderr line-by-line as the subprocess runs, rather
than holding silent until exit. The final ``tools/call`` result still
carries the full ``SandboxResult`` so non-streaming clients keep working.
"""

from __future__ import annotations

import itertools
import json
import sys
from typing import Any, TextIO

from biobabel.mcp.server import BiobabelMCPServer

PROTOCOL_VERSION = "2024-11-05"


class StdioTransport:
    def __init__(
        self,
        server: BiobabelMCPServer,
        *,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
    ) -> None:
        self.server = server
        self._stdin = stdin or sys.stdin
        self._stdout = stdout or sys.stdout

    def serve_forever(self) -> None:
        for line in self._stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError as exc:
                self._send(_jsonrpc_error(None, -32700, f"parse error: {exc}"))
                continue
            self._handle(req)

    def _handle(self, req: dict[str, Any]) -> None:
        if not isinstance(req, dict) or req.get("jsonrpc") != "2.0":
            self._send(_jsonrpc_error(None, -32600, "invalid request"))
            return
        method = req.get("method", "")
        msg_id = req.get("id")
        params = req.get("params") or {}

        if method == "initialize":
            self._send(
                _jsonrpc_result(
                    msg_id,
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "serverInfo": {"name": "biobabel", "version": "0.1.0"},
                        "capabilities": {"tools": {"listChanged": False}},
                    },
                )
            )
        elif method == "notifications/initialized":
            return  # no response for notifications
        elif method == "tools/list":
            tools = [
                {
                    "name": name,
                    "description": self.server.tool(name).description,
                    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True},
                }
                for name in self.server.tool_names
            ]
            self._send(_jsonrpc_result(msg_id, {"tools": tools}))
        elif method == "tools/call":
            self._handle_tools_call(msg_id, params)
        else:
            self._send(_jsonrpc_error(msg_id, -32601, f"method not found: {method}"))

    def _handle_tools_call(self, msg_id: Any, params: dict[str, Any]) -> None:
        name = params.get("name", "")
        args = params.get("arguments") or {}
        progress_token = _extract_progress_token(params)
        emitter = self._make_progress_emitter(progress_token) if progress_token is not None else None

        try:
            envelope = self.server.call(name, progress=emitter, **args)
        except Exception as exc:  # noqa: BLE001 — last-resort guard so a buggy
            # handler can't kill the stdio loop; the raised exception is
            # surfaced to the LLM as a structured error envelope with the
            # full type+message rather than swallowed silently.
            envelope = {
                "ok": False,
                "tool_name": name,
                "error_code": "exception",
                "message": f"{type(exc).__name__}: {exc}",
            }
        self._send(
            _jsonrpc_result(
                msg_id,
                {
                    "content": [
                        {"type": "text", "text": json.dumps(envelope, ensure_ascii=False)}
                    ],
                    "isError": not envelope.get("ok", True),
                },
            )
        )

    def _make_progress_emitter(self, progress_token: Any):
        """Build a callable that forwards each payload as a progress notification.

        The MCP spec's ``notifications/progress`` carries ``progressToken``
        and ``progress`` (a monotone counter; we use the chunk index since
        total chunks are unknowable in advance). The chunk payload is
        JSON-encoded into ``message`` so the client can recover ``stream``
        and ``text`` losslessly.
        """
        counter = itertools.count(start=1)

        def emit(payload: dict[str, Any]) -> None:
            self._send(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/progress",
                    "params": {
                        "progressToken": progress_token,
                        "progress": next(counter),
                        "message": json.dumps(payload, ensure_ascii=False),
                    },
                }
            )

        return emit

    def _send(self, msg: dict[str, Any]) -> None:
        line = json.dumps(msg, ensure_ascii=False)
        self._stdout.write(line + "\n")
        self._stdout.flush()


def _extract_progress_token(params: dict[str, Any]) -> Any:
    meta = params.get("_meta")
    if not isinstance(meta, dict):
        return None
    return meta.get("progressToken")


def _jsonrpc_result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _jsonrpc_error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}
