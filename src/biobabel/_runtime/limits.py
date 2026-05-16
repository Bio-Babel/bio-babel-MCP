"""Runtime resource limits — defaults per §7.1."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RuntimeLimits:
    # Per-session capacity
    max_adata_per_session: int = 50
    max_artifacts_per_session: int = 500

    # TTL (seconds)
    event_ttl_seconds: int = 24 * 3600
    trace_ttl_seconds: int = 24 * 3600
    artifact_ttl_seconds: int = 7 * 24 * 3600
    session_ttl_seconds: int = 24 * 3600

    # Per-call execution
    default_timeout_s: int = 60
    hard_timeout_s: int = 300
    max_memory_mb: int = 4096
    max_stdout_kb: int = 100
    max_output_file_mb: int = 50
    max_open_files: int = 256
