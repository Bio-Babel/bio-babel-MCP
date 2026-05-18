"""Group 8 — Meta (3 tools)."""

from __future__ import annotations

from typing import Any

from biobabel._registry.builder import Registry
from biobabel._runtime.session import SessionStore
from biobabel.mcp.envelope import success


def list_tools(tool_names: list[str]) -> dict[str, Any]:
    return success(
        "biobabel.list_tools",
        summary=f"{len(tool_names)} tools",
        outputs={"tools": tool_names},
    )


def health(registry: Registry, sessions: SessionStore) -> dict[str, Any]:
    warnings: list[str] = []
    for err in registry.errors:
        warnings.append(f"[{err.kind}] {err.name} ({err.distribution}): {err.error}")
    handles_by_session: dict[str, dict[str, list[str]]] = {
        sid: sess.list_handles() for sid, sess in sessions.iter_sessions()
    }
    return success(
        "biobabel.health",
        summary=(
            f"{len(registry.packages)} packages, "
            f"{len(handles_by_session)} sessions, "
            f"{len(warnings)} discovery warning(s)"
        ),
        outputs={
            "packages": len(registry.packages),
            "sessions": len(handles_by_session),
            "handles_by_session": handles_by_session,
            "discovery_errors": [err.__dict__ for err in registry.errors],
        },
        warnings=warnings,
    )


def list_traces(
    sessions: SessionStore, *, session_id: str | None = None, n: int = 50
) -> dict[str, Any]:
    sess = sessions.get(session_id) if session_id is not None else sessions.get_default()
    if sess is None:
        summary = (
            "session not found, returning empty"
            if session_id is not None
            else "no default session yet, returning empty"
        )
        return success(
            "biobabel.list_traces",
            summary=summary,
            outputs={"session_id": session_id, "traces": []},
        )
    traces = sess.list_traces(n=n)
    return success(
        "biobabel.list_traces",
        summary=f"{len(traces)} trace(s)",
        outputs={
            "session_id": sess.session_id,
            "traces": [
                {
                    "trace_id": t.trace_id,
                    "tool_name": t.tool_name,
                    "started_at": t.started_at.isoformat(),
                    "duration_ms": t.duration_ms,
                    "ok": t.ok,
                    "error_code": t.error_code,
                    "handle_refs_in": t.handle_refs_in,
                    "handle_refs_out": t.handle_refs_out,
                    "args_summary": t.args_summary,
                }
                for t in traces
            ]
        },
    )
