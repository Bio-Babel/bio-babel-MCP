"""Stdio JSON-RPC 2.0 transport, MCP-compatible at the wire level.

We deliberately avoid hard-binding to a specific MCP SDK so that:

  * Smoke tests can drive the server without external deps.
  * Users can wire any MCP client (Claude Code, Cursor, Continue, ...) that
    speaks the standard `initialize`/`tools/list`/`tools/call` protocol.
"""

from __future__ import annotations

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
            name = params.get("name", "")
            args = params.get("arguments") or {}
            try:
                envelope = self.server.call(name, **args)
            except Exception as exc:  # noqa: BLE001
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
        else:
            self._send(_jsonrpc_error(msg_id, -32601, f"method not found: {method}"))

    def _send(self, msg: dict[str, Any]) -> None:
        line = json.dumps(msg, ensure_ascii=False)
        self._stdout.write(line + "\n")
        self._stdout.flush()


def _jsonrpc_result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _jsonrpc_error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}
