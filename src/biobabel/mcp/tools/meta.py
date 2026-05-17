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


def list_traces(sessions: SessionStore, *, session_id: str, n: int = 50) -> dict[str, Any]:
    sess = sessions.get(session_id)
    if sess is None:
        return success(
            "biobabel.list_traces",
            summary="session not found, returning empty",
            outputs={"traces": []},
        )
    traces = sess.list_traces(n=n)
    return success(
        "biobabel.list_traces",
        summary=f"{len(traces)} trace(s)",
        outputs={
            "traces": [
                {
                    "trace_id": t.trace_id,
                    "tool_name": t.tool_name,
                    "started_at": t.started_at.isoformat(),
                    "duration_ms": t.duration_ms,
                    "ok": t.ok,
                    "error_code": t.error_code,
                }
                for t in traces
            ]
        },
    )
