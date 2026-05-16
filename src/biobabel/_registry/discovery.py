"""Entry-point only manifest discovery.

Per the §0.4 hard constraint: there is NO reflection fallback. A package is
only visible to biobabel if it registers a `biobabel.manifest` entry point
that returns a :class:`PackageManifest`.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import EntryPoint, distributions, entry_points
from typing import Callable

from biobabel.manifest_api import PackageManifest

ENTRY_POINT_GROUP = "biobabel.manifest"


@dataclass(frozen=True)
class DiscoveredManifest:
    """A successfully discovered manifest, with its provenance."""

    import_name: str            # the entry-point name (e.g. "grid_py")
    distribution: str           # PyPI distribution (e.g. "rgrid-python")
    distribution_version: str
    manifest: PackageManifest


@dataclass(frozen=True)
class DiscoveryError:
    """A failed discovery attempt — entry point existed but couldn't be loaded."""

    import_name: str
    distribution: str
    error: str


def discover() -> tuple[list[DiscoveredManifest], list[DiscoveryError]]:
    """Load all `biobabel.manifest` entry points.

    Returns ``(successes, errors)``. Errors are surfaced rather than swallowed,
    so the CLI / MCP `health` tool can warn the user about broken packages.
    """
    eps = entry_points(group=ENTRY_POINT_GROUP)
    dist_index = _build_distribution_index()

    successes: list[DiscoveredManifest] = []
    errors: list[DiscoveryError] = []

    for ep in eps:
        dist_name, dist_version = dist_index.get(ep, ("unknown", "0.0.0"))
        try:
            factory = ep.load()
        except Exception as exc:
            errors.append(DiscoveryError(ep.name, dist_name, f"entry-point load failed: {exc!r}"))
            continue

        manifest = _invoke_factory(factory)
        if isinstance(manifest, BaseException):
            errors.append(DiscoveryError(ep.name, dist_name, f"factory raised: {manifest!r}"))
            continue
        if not isinstance(manifest, PackageManifest):
            errors.append(
                DiscoveryError(
                    ep.name,
                    dist_name,
                    f"factory returned {type(manifest).__name__}, expected PackageManifest",
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


def _build_distribution_index() -> dict[EntryPoint, tuple[str, str]]:
    """Map each biobabel.manifest entry point back to its providing distribution."""
    index: dict[EntryPoint, tuple[str, str]] = {}
    for dist in distributions():
        meta = dist.metadata
        name = meta["Name"] if meta and "Name" in meta else "unknown"
        version = dist.version or "0.0.0"
        for ep in dist.entry_points:
            if ep.group == ENTRY_POINT_GROUP:
                index[ep] = (name, version)
    return index
