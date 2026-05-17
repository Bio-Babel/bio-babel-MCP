"""Stable SHA-256 over a PackageManifest.

Used by `_exporters/skills.py` to stamp generated SKILL.md files with a
content fingerprint for provenance. The hash is deterministic for the
same manifest content: serialize the model_dump with sorted keys, then
SHA-256 the resulting bytes.
"""

from __future__ import annotations

import hashlib
import json

from biobabel.manifest_api import PackageManifest


def manifest_sha256(manifest: PackageManifest) -> str:
    """Stable hash: dump model_dump() with sorted keys, separators-stripped."""
    payload = json.dumps(
        manifest.model_dump(mode="json"),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
