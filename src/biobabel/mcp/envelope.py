"""Structured response envelope shared by all 20 MCP tools."""

from __future__ import annotations

from typing import Any


def success(
    tool_name: str,
    *,
    summary: str = "",
    outputs: dict[str, Any] | None = None,
    state_updates: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "tool_name": tool_name,
        "summary": summary,
        "outputs": outputs or {},
        "state_updates": state_updates or {},
        "warnings": warnings or [],
    }


def error(
    tool_name: str,
    *,
    error_code: str,
    message: str,
    details: dict[str, Any] | None = None,
    suggested_next_tools: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "tool_name": tool_name,
        "error_code": error_code,
        "message": message,
        "details": details or {},
        "suggested_next_tools": suggested_next_tools or [],
    }
