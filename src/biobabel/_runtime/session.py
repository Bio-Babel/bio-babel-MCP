"""Session: per-conversation workspace of handles + artifacts + traces."""

from __future__ import annotations

import shutil
import tempfile
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from biobabel._runtime.artifacts import ArtifactHandle
from biobabel._runtime.limits import RuntimeLimits
from biobabel._runtime.trace import TraceRecord, TraceStore


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class AdataHandle:
    adata_id: str
    path: Path | None = None
    shape: tuple[int, int] | None = None
    obs_keys: list[str] = field(default_factory=list)
    obsm_keys: list[str] = field(default_factory=list)
    var_keys: list[str] = field(default_factory=list)
    uns_keys: list[str] = field(default_factory=list)
    layers: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DfHandle:
    df_id: str
    path: Path | None = None
    shape: tuple[int, int] | None = None
    columns: list[str] = field(default_factory=list)
    dtypes: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PlotHandle:
    plot_id: str
    path: Path
    width_px: int = 0
    height_px: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Session:
    session_id: str
    workspace: Path
    limits: RuntimeLimits
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    _adata: dict[str, AdataHandle] = field(default_factory=dict)
    _dataframes: dict[str, DfHandle] = field(default_factory=dict)
    _plots: dict[str, PlotHandle] = field(default_factory=dict)
    _artifacts: dict[str, ArtifactHandle] = field(default_factory=dict)
    _events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=10_000))
    _traces: TraceStore = field(default_factory=TraceStore)
    _lock: RLock = field(default_factory=RLock)

    def add_adata(self, h: AdataHandle) -> None:
        with self._lock:
            if len(self._adata) >= self.limits.max_adata_per_session:
                raise RuntimeError("session adata cap reached")
            self._adata[h.adata_id] = h

    def get_adata(self, adata_id: str) -> AdataHandle | None:
        return self._adata.get(adata_id)

    def add_df(self, h: DfHandle) -> None:
        with self._lock:
            self._dataframes[h.df_id] = h

    def get_df(self, df_id: str) -> DfHandle | None:
        return self._dataframes.get(df_id)

    def add_plot(self, h: PlotHandle) -> None:
        with self._lock:
            self._plots[h.plot_id] = h

    def add_artifact(self, a: ArtifactHandle) -> None:
        with self._lock:
            if len(self._artifacts) >= self.limits.max_artifacts_per_session:
                raise RuntimeError("session artifact cap reached")
            self._artifacts[a.artifact_id] = a

    def get_artifact(self, artifact_id: str) -> ArtifactHandle | None:
        return self._artifacts.get(artifact_id)

    def list_handles(self) -> dict[str, list[str]]:
        return {
            "adata": list(self._adata),
            "dataframes": list(self._dataframes),
            "plots": list(self._plots),
            "artifacts": list(self._artifacts),
        }

    def record_trace(self, rec: TraceRecord) -> None:
        rec.session_id = self.session_id
        self._traces.record(rec)

    def list_traces(self, n: int = 50) -> list[TraceRecord]:
        return self._traces.list_recent(n)


class SessionStore:
    """Process-wide session manager.

    Sessions are no longer publicly created by the LLM (the
    ``biobabel.create_session`` MCP tool was removed). Instead, the first
    runtime tool call without an explicit ``session_id`` triggers
    :meth:`get_or_create_default`, which lazily creates a single default
    session per process and reuses it on subsequent calls. Power users
    that need multiple parallel sessions still get them by calling
    :meth:`create` directly through internal Python — but the LLM-facing
    MCP surface no longer exposes session lifecycle as a step.
    """

    def __init__(self, root: Path | None = None, limits: RuntimeLimits | None = None) -> None:
        self._root = root or Path(tempfile.mkdtemp(prefix="biobabel_sessions_"))
        self._root.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, Session] = {}
        self._lock = RLock()
        self._limits = limits or RuntimeLimits()
        self._default_id: str | None = None

    @property
    def root(self) -> Path:
        return self._root

    def create(self) -> Session:
        sid = _new_id("sess")
        with self._lock:
            ws = self._root / sid
            ws.mkdir(parents=True, exist_ok=True)
            sess = Session(session_id=sid, workspace=ws, limits=self._limits)
            self._sessions[sid] = sess
            return sess

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def require(self, session_id: str) -> Session:
        sess = self.get(session_id)
        if sess is None:
            raise KeyError(f"session not found: {session_id}")
        return sess

    def get_or_create_default(self) -> Session:
        """Return the per-process default session, creating it on first use.

        If a prior default was created and then deleted via :meth:`delete`,
        the next call here transparently allocates a fresh one rather
        than raising — that fits the "session is plumbing, never the
        LLM's problem" stance of the trim.
        """
        with self._lock:
            if self._default_id is not None and self._default_id in self._sessions:
                return self._sessions[self._default_id]
            sess = self.create()
            self._default_id = sess.session_id
            return sess

    def get_default(self) -> Session | None:
        """Return the existing default session without creating one.

        ``list_traces`` uses this read-only path so asking for traces before
        any runtime call does not accidentally create an empty session.
        """
        with self._lock:
            if self._default_id is None:
                return None
            return self._sessions.get(self._default_id)

    def list_sessions(self) -> list[str]:
        return list(self._sessions)

    def iter_sessions(self) -> list[tuple[str, Session]]:
        """Snapshot of (session_id, Session) pairs for health reporting."""
        with self._lock:
            return list(self._sessions.items())

    def delete(self, session_id: str) -> None:
        with self._lock:
            sess = self._sessions.pop(session_id, None)
            if sess is not None:
                shutil.rmtree(sess.workspace, ignore_errors=True)
            if self._default_id == session_id:
                self._default_id = None

    def shutdown(self) -> None:
        with self._lock:
            for sid in list(self._sessions):
                self.delete(sid)
            shutil.rmtree(self._root, ignore_errors=True)
