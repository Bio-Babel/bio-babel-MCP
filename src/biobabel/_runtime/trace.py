"""Trace records — ring buffer of recent MCP calls."""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class TraceRecord:
    trace_id: str = field(default_factory=lambda: f"trace_{uuid.uuid4().hex[:12]}")
    session_id: str = ""
    tool_name: str = ""
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: float = 0.0
    ok: bool = True
    error_code: str = ""
    handle_refs_in: list[str] = field(default_factory=list)
    handle_refs_out: list[str] = field(default_factory=list)
    args_summary: dict[str, object] = field(default_factory=dict)


class TraceStore:
    """Fixed-size ring buffer of trace records."""

    def __init__(self, maxlen: int = 5000) -> None:
        self._records: deque[TraceRecord] = deque(maxlen=maxlen)

    def record(self, rec: TraceRecord) -> None:
        self._records.append(rec)

    def list_recent(self, n: int = 50) -> list[TraceRecord]:
        return list(self._records)[-n:][::-1]

    def __len__(self) -> int:
        return len(self._records)
