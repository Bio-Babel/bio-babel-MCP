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
    """Process-wide session manager."""

    def __init__(self, root: Path | None = None, limits: RuntimeLimits | None = None) -> None:
        self._root = root or Path(tempfile.mkdtemp(prefix="biobabel_sessions_"))
        self._root.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, Session] = {}
        self._lock = RLock()
        self._limits = limits or RuntimeLimits()

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

    def list_sessions(self) -> list[str]:
        return list(self._sessions)

    def delete(self, session_id: str) -> None:
        with self._lock:
            sess = self._sessions.pop(session_id, None)
            if sess is not None:
                shutil.rmtree(sess.workspace, ignore_errors=True)

    def shutdown(self) -> None:
        with self._lock:
            for sid in list(self._sessions):
                self.delete(sid)
            shutil.rmtree(self._root, ignore_errors=True)
