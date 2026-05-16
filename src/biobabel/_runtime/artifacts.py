"""Artifact handles with provenance per §7.2."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ArtifactHandle:
    artifact_id: str
    path: Path
    content_type: str
    artifact_type: str          # "image/png", "csv", "h5ad", "json", ...
    source_tool: str
    source_code_hash: str
    package_versions: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    content_hash: str = ""
    size_bytes: int = 0
    metadata: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_path(
        cls,
        artifact_id: str,
        path: Path,
        *,
        content_type: str,
        artifact_type: str,
        source_tool: str,
        source_code_hash: str = "",
        package_versions: dict[str, str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ArtifactHandle:
        data = path.read_bytes()
        return cls(
            artifact_id=artifact_id,
            path=path,
            content_type=content_type,
            artifact_type=artifact_type,
            source_tool=source_tool,
            source_code_hash=source_code_hash,
            package_versions=dict(package_versions or {}),
            content_hash=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            metadata=dict(metadata or {}),
        )
