"""Compare two RegistryLocks → set of changed packages, signaling API drift."""

from __future__ import annotations

from dataclasses import dataclass, field

from biobabel._registry.lockfile import RegistryLock


@dataclass
class RegistryDiff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[tuple[str, str, str]] = field(default_factory=list)
    # (import_name, old_sha256, new_sha256)

    @property
    def ok(self) -> bool:
        return not (self.added or self.removed or self.changed)


def diff_registries(old: RegistryLock, new: RegistryLock) -> RegistryDiff:
    old_map = {e.import_name: e for e in old.entries}
    new_map = {e.import_name: e for e in new.entries}
    diff = RegistryDiff()

    for name in sorted(new_map):
        if name not in old_map:
            diff.added.append(name)
        elif old_map[name].manifest_sha256 != new_map[name].manifest_sha256:
            diff.changed.append(
                (name, old_map[name].manifest_sha256, new_map[name].manifest_sha256)
            )
    for name in sorted(old_map):
        if name not in new_map:
            diff.removed.append(name)
    return diff
