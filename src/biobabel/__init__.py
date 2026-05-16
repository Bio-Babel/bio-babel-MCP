"""biobabel — agent control plane for the Bio-Babel ecosystem.

The only stable Python surface for upstream package authors is
:mod:`biobabel.manifest_api`. Everything else (`_registry`, `_runtime`, ...)
is private.
"""

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
    RPackageRef,
    Recipe,
    TaskTrigger,
    WorkflowContract,
    WorkflowStep,
)

__version__ = "0.1.0"
SCHEMA_VERSION = 1

__all__ = [
    "AntiPatternDetection",
    "AntiPatternSpec",
    "CompositionSpec",
    "ConceptSpec",
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
