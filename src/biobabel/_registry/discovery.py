"""Entry-point only manifest + detector discovery.

There is NO reflection fallback for either kind. A package is only visible
to biobabel if it registers the appropriate entry point.

Two entry-point groups:

- ``biobabel.manifest``   →  the upstream package's :class:`PackageManifest`
- ``biobabel.detectors``  →  a :data:`DetectorFn` referenced by an
                              ``AntiPatternSpec.detection.detector_id``
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import EntryPoint, distributions, entry_points

from biobabel.detector_api import DetectorFn
from biobabel.manifest_api import PackageManifest

MANIFEST_ENTRY_POINT_GROUP = "biobabel.manifest"
DETECTOR_ENTRY_POINT_GROUP = "biobabel.detectors"

# Backward-compatible alias; some older internal callers reference this name.
ENTRY_POINT_GROUP = MANIFEST_ENTRY_POINT_GROUP


@dataclass(frozen=True)
class DiscoveredManifest:
    """A successfully discovered manifest, with its provenance."""

    import_name: str            # the entry-point name (e.g. "grid_py")
    distribution: str           # PyPI distribution (e.g. "rgrid-python")
    distribution_version: str
    manifest: PackageManifest


@dataclass(frozen=True)
class DiscoveredDetector:
    """A successfully discovered AST detector callable, with its provenance."""

    detector_id: str            # the entry-point name (e.g. "rgrid.for_loop_calls")
    distribution: str
    distribution_version: str
    fn: DetectorFn


@dataclass(frozen=True)
class DiscoveryError:
    """A failed discovery or registration attempt.

    Three failure modes share this record type so the health tool can
    surface them uniformly:

    - ``kind="manifest"``  — entry point existed but the manifest factory
                              failed to load or returned the wrong type.
    - ``kind="detector"``  — same for a detector entry point.
    - ``kind="duplicate"`` — two distributions tried to register the same
                              identifier (package import_name, function id,
                              concept id, idiom id, anti-pattern id, workflow
                              id, or detector id). The first registration
                              keeps the slot; the second is skipped.
    """

    name: str                   # import_name OR detector_id OR colliding id
    distribution: str
    error: str
    kind: str = "manifest"      # "manifest" | "detector" | "duplicate"


def discover() -> tuple[list[DiscoveredManifest], list[DiscoveryError]]:
    """Load all ``biobabel.manifest`` entry points.

    Returns ``(successes, errors)``. Errors are surfaced rather than swallowed
    so the CLI / MCP ``health`` tool can warn the user about broken packages.
    """
    dist_index = _build_distribution_index(MANIFEST_ENTRY_POINT_GROUP)
    successes: list[DiscoveredManifest] = []
    errors: list[DiscoveryError] = []

    for ep in entry_points(group=MANIFEST_ENTRY_POINT_GROUP):
        dist_name, dist_version = dist_index.get(ep, ("unknown", "0.0.0"))
        try:
            factory = ep.load()
        except Exception as exc:
            errors.append(DiscoveryError(ep.name, dist_name, f"entry-point load failed: {exc!r}", kind="manifest"))
            continue

        manifest = _invoke_factory(factory)
        if isinstance(manifest, BaseException):
            errors.append(DiscoveryError(ep.name, dist_name, f"factory raised: {manifest!r}", kind="manifest"))
            continue
        if not isinstance(manifest, PackageManifest):
            errors.append(
                DiscoveryError(
                    ep.name,
                    dist_name,
                    f"factory returned {type(manifest).__name__}, expected PackageManifest",
                    kind="manifest",
                )
            )
            continue

        successes.append(
            DiscoveredManifest(
                import_name=ep.name,
                distribution=dist_name,
                distribution_version=dist_version,
                manifest=manifest,
            )
        )

    return successes, errors


def discover_detectors() -> tuple[list[DiscoveredDetector], list[DiscoveryError]]:
    """Load all ``biobabel.detectors`` entry points.

    Each entry-point name is the ``detector_id`` referenced from
    :class:`AntiPatternSpec.detection.detector_id`. The entry-point's
    callable target must satisfy the :data:`DetectorFn` signature; a
    non-callable target is recorded as a discovery error.
    """
    dist_index = _build_distribution_index(DETECTOR_ENTRY_POINT_GROUP)
    successes: list[DiscoveredDetector] = []
    errors: list[DiscoveryError] = []

    for ep in entry_points(group=DETECTOR_ENTRY_POINT_GROUP):
        dist_name, dist_version = dist_index.get(ep, ("unknown", "0.0.0"))
        try:
            target = ep.load()
        except Exception as exc:
            errors.append(DiscoveryError(ep.name, dist_name, f"entry-point load failed: {exc!r}", kind="detector"))
            continue
        if not callable(target):
            errors.append(
                DiscoveryError(
                    ep.name,
                    dist_name,
                    f"target is {type(target).__name__}, not callable",
                    kind="detector",
                )
            )
            continue
        successes.append(
            DiscoveredDetector(
                detector_id=ep.name,
                distribution=dist_name,
                distribution_version=dist_version,
                fn=target,
            )
        )

    return successes, errors


def _invoke_factory(factory: Callable[[], PackageManifest] | PackageManifest) -> object:
    """Allow the entry point to be either the manifest itself or a factory callable."""
    if isinstance(factory, PackageManifest):
        return factory
    if callable(factory):
        try:
            return factory()
        except Exception as exc:  # noqa: BLE001 — surfaced as DiscoveryError
            return exc
    return TypeError(f"{factory!r} is neither a PackageManifest nor a callable")


def _build_distribution_index(group: str) -> dict[EntryPoint, tuple[str, str]]:
    """Map each entry point in *group* back to its providing distribution."""
    index: dict[EntryPoint, tuple[str, str]] = {}
    for dist in distributions():
        meta = dist.metadata
        name = meta["Name"] if meta and "Name" in meta else "unknown"
        version = dist.version or "0.0.0"
        for ep in dist.entry_points:
            if ep.group == group:
                index[ep] = (name, version)
    return index
