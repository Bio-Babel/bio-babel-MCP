"""Registry: discover and build the set of installed Bio-Babel packages + detectors.

Two entry-point groups feed the registry: ``biobabel.manifest`` for upstream
package manifests and ``biobabel.detectors`` for producer-registered AST
detectors. ``sha.manifest_sha256`` is a stable content hash retained for
provenance stamps in generated SKILL.md files.
"""

from biobabel._registry.builder import Registry, build_registry
from biobabel._registry.discovery import (
    DiscoveredDetector,
    DiscoveredManifest,
    DiscoveryError,
    discover,
    discover_detectors,
)
from biobabel._registry.sha import manifest_sha256

__all__ = [
    "DiscoveredDetector",
    "DiscoveredManifest",
    "DiscoveryError",
    "Registry",
    "build_registry",
    "discover",
    "discover_detectors",
    "manifest_sha256",
]
