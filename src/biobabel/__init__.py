"""biobabel — agent control plane for the Bio-Babel ecosystem.

Stable public Python surfaces for upstream package authors:

- :mod:`biobabel.manifest_api` — Pydantic models for the ``_biobabel/``
  contract (PackageManifest, FunctionContract, AntiPatternSpec, ...).
- :mod:`biobabel.detector_api` — types for callables registered via the
  ``biobabel.detectors`` entry-point group (DetectorMatch, DetectorFn).
  Added in schema v2.

Everything else (``_registry``, ``_runtime``, ``_concept``, ...) is private.
"""

from biobabel.detector_api import DetectorFn, DetectorMatch
from biobabel.manifest_api import (
    AntiPatternDetection,
    AntiPatternSpec,
    CompositionSpec,
    ConceptSpec,
    ExtensionRef,
    FailureFix,
    FunctionContract,
    IdiomSpec,
    InternalStep,
    MentalModel,
    PackageManifest,
    Parameter,
    ParameterSet,
    ProvidedExtension,
    Recipe,
    RPackageRef,
    TaskTrigger,
    WorkflowContract,
    WorkflowStep,
)

__version__ = "0.2.0"
SCHEMA_VERSION = 2

__all__ = [
    "AntiPatternDetection",
    "AntiPatternSpec",
    "CompositionSpec",
    "ConceptSpec",
    "DetectorFn",
    "DetectorMatch",
    "ExtensionRef",
    "FailureFix",
    "FunctionContract",
    "IdiomSpec",
    "InternalStep",
    "MentalModel",
    "PackageManifest",
    "Parameter",
    "ParameterSet",
    "ProvidedExtension",
    "RPackageRef",
    "Recipe",
    "SCHEMA_VERSION",
    "TaskTrigger",
    "WorkflowContract",
    "WorkflowStep",
    "__version__",
]
