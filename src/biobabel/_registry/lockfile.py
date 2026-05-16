"""Registry lockfile: sha256 over each manifest for drift detection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from biobabel._registry.builder import Registry
from biobabel.manifest_api import PackageManifest

LOCK_VERSION = 1


@dataclass(frozen=True)
class LockEntry:
    import_name: str
    distribution: str
    distribution_version: str
    contract_class: str
    manifest_sha256: str


@dataclass
class RegistryLock:
    lock_version: int = LOCK_VERSION
    generated_at: str = ""
    entries: list[LockEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "lock_version": self.lock_version,
            "generated_at": self.generated_at,
            "entries": [asdict(e) for e in self.entries],
        }


def manifest_sha256(manifest: PackageManifest) -> str:
    """Stable hash: dump model_dump() with sorted keys."""
    payload = json.dumps(
        manifest.model_dump(mode="json"),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_lock(registry: Registry) -> RegistryLock:
    entries = []
    for import_name in sorted(registry.packages):
        d = registry.packages[import_name]
        entries.append(
            LockEntry(
                import_name=d.import_name,
                distribution=d.distribution,
                distribution_version=d.distribution_version,
                contract_class=d.manifest.contract_class,
                manifest_sha256=manifest_sha256(d.manifest),
            )
        )
    return RegistryLock(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        entries=entries,
    )


def write_lock(lock: RegistryLock, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(lock.to_dict(), sort_keys=False), encoding="utf-8")


def read_lock(path: Path) -> RegistryLock:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    entries = [LockEntry(**e) for e in raw.get("entries", [])]
    return RegistryLock(
        lock_version=raw.get("lock_version", LOCK_VERSION),
        generated_at=raw.get("generated_at", ""),
        entries=entries,
    )
