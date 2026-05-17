"""Pydantic v2 models for the biobabel contract.

Schema version 2 (current). Additive-only within v2.

v1 → v2 break: ``AntiPatternDetection`` replaced the mini-DSL string
``ast_pattern: "<kind>:<args>"`` with structured ``detector_id`` +
``args`` so that producers can register their own AST detectors via the
``biobabel.detectors`` entry-point group.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ContractClass = Literal["analysis", "grammar", "mixed"]

ExtensionKind = Literal[
    "geom", "stat", "scale", "theme", "operator", "annotation", "facet"
]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# --- requires / writes token grammar --------------------------------------
#
# Both ``FunctionContract`` and ``WorkflowStep`` describe AnnData state with
# a flat list of canonical tokens. Each token is one of:
#
#   ``<slot>.<key>``  — state-presence claim. ``slot`` is one of the AnnData
#                       containers; ``key`` is the column / matrix / element
#                       name. Dotted keys inside ``<key>`` are allowed
#                       (e.g. ``uns.monocle3.preprocess``).
#   ``X:<semantic>``  — semantic claim about ``adata.X`` content, independent
#                       of slot presence. ``X:raw_counts`` is runtime-checkable
#                       (integer dtype + non-negative); the others are
#                       advisory and matched against a producer-planted
#                       ``uns.normalization`` breadcrumb.
#
# A ``mode="before"`` validator additionally accepts the legacy nested-dict
# shape (``{adata: {slot: [...], X: "raw_counts"}}``, ``{df: {...}}``,
# ``{}``) and flattens it into the canonical token list internally. The
# producer's YAML is *not* mutated; only biobabel's in-memory representation
# is normalized. This keeps producers off the schema-bump treadmill while
# letting the planner consume a single uniform shape.

_VALID_STATE_SLOTS: frozenset[str] = frozenset(
    {"obs", "obsm", "var", "varm", "uns", "layers"}
)
_VALID_X_SEMANTICS: frozenset[str] = frozenset(
    {"raw_counts", "lognorm", "normalized"}
)
_LEGACY_CONTAINER_ALIASES: frozenset[str] = frozenset(
    # ``query_adata`` / ``ref_adata`` appear in monocle3's label-transfer
    # functions, which take two AnnDatas (query + reference). biobabel's
    # planner consumes a single ``AdataHandle`` and has no concept of
    # "query vs ref", so these are absorbed into the same flat token list.
    # The per-adata distinction is preserved in the producer YAML; it is
    # simply not consumed at this layer.
    {"adata", "anndata", "df", "dataframe", "query_adata", "ref_adata"}
)


def _validate_state_token(t: object) -> str:
    if not isinstance(t, str) or not t:
        raise ValueError(
            f"requires/writes entry must be a non-empty string, got {t!r}"
        )
    if t.startswith("X:"):
        sem = t[2:]
        if sem not in _VALID_X_SEMANTICS:
            raise ValueError(
                f"requires/writes token {t!r}: unknown X semantic {sem!r}. "
                f"Expected one of {sorted(_VALID_X_SEMANTICS)}"
            )
        return t
    if "." in t:
        slot, key = t.split(".", 1)
        if slot not in _VALID_STATE_SLOTS:
            raise ValueError(
                f"requires/writes token {t!r}: unknown slot {slot!r}. "
                f"Expected one of {sorted(_VALID_STATE_SLOTS)} or 'X:<semantic>'"
            )
        if not key:
            raise ValueError(
                f"requires/writes token {t!r}: empty key after slot"
            )
        return t
    raise ValueError(
        f"requires/writes token {t!r}: must be '<slot>.<key>' or 'X:<semantic>'"
    )


def _absorb_legacy_state_dict(d: dict[str, Any]) -> list[str]:
    if not d:
        return []
    container_present = _LEGACY_CONTAINER_ALIASES & d.keys()
    if container_present:
        # Multiple containers (e.g. ``query_adata`` + ``ref_adata``) are
        # merged into a single flat token list; see the comment on
        # ``_LEGACY_CONTAINER_ALIASES`` for why this is loss-free at the
        # consumer layer.
        extras = set(d.keys()) - _LEGACY_CONTAINER_ALIASES
        if extras:
            raise ValueError(
                f"legacy requires/writes dict has unexpected sibling keys "
                f"{sorted(extras)} alongside containers "
                f"{sorted(container_present)}"
            )
        inners: list[dict[str, Any]] = []
        for container in container_present:
            inner = d[container]
            if not isinstance(inner, dict):
                raise ValueError(
                    f"legacy requires/writes: {container!r} must wrap a dict, "
                    f"got {type(inner).__name__}"
                )
            inners.append(inner)
    else:
        inners = [d]

    out: list[str] = []
    seen: set[str] = set()
    for inner in inners:
        for key, val in inner.items():
            tokens: list[str] = []
            if key == "X":
                if not isinstance(val, str):
                    raise ValueError(
                        f"legacy requires/writes: X must be a string, got "
                        f"{type(val).__name__}"
                    )
                tokens.append(f"X:{val}")
            elif key in _VALID_STATE_SLOTS:
                if isinstance(val, list):
                    for k in val:
                        if not isinstance(k, str) or not k:
                            raise ValueError(
                                f"legacy requires/writes: {key!r} list contains "
                                f"non-string or empty entry {k!r}"
                            )
                        tokens.append(f"{key}.{k}")
                elif isinstance(val, str):
                    tokens.append(f"{key}.{val}")
                else:
                    raise ValueError(
                        f"legacy requires/writes: {key!r} must be list or string, "
                        f"got {type(val).__name__}"
                    )
            else:
                raise ValueError(
                    f"legacy requires/writes: unknown inner key {key!r}; "
                    f"expected one of {sorted(_VALID_STATE_SLOTS)} or 'X'"
                )
            for t in tokens:
                if t not in seen:
                    seen.add(t)
                    out.append(t)
    return out


def _canonicalize_state(v: object) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [_validate_state_token(t) for t in v]
    if isinstance(v, dict):
        return [_validate_state_token(t) for t in _absorb_legacy_state_dict(v)]
    raise ValueError(
        f"requires/writes must be a list of strings or a legacy nested dict; "
        f"got {type(v).__name__}"
    )


class TaskTrigger(_Frozen):
    intent: str
    confidence: float = 0.8


class RPackageRef(_Frozen):
    package: str
    repo: str = ""
    version_or_commit: str = ""
    fidelity: Literal["full", "partial", "subset"] = "partial"


class Recipe(_Frozen):
    id: str
    task_tags: list[str] = Field(default_factory=list)
    path: str
    description: str = ""
    inputs_schema: dict[str, Any] = Field(default_factory=dict)
    outputs_schema: dict[str, Any] = Field(default_factory=dict)
    expected_artifacts: list[str] = Field(default_factory=list)


# --- Class A: state-machine contract --------------------------------------


class Parameter(_Frozen):
    name: str
    type: str = ""
    required: bool = False
    default: Any = None
    description: str = ""


class FailureFix(_Frozen):
    when: str
    suggest: list[str]
    explanation: str = ""


class InternalStep(_Frozen):
    """For monolithic Class A packages (e.g. copykat, DDRTree)."""

    id: str
    description: str
    typical_failures: list[str] = Field(default_factory=list)


class ParameterSet(_Frozen):
    """For huge-parameter functions (e.g. pheatmap, Heatmap)."""

    name: str
    description: str
    params: dict[str, Any]
    recipe: str = ""


class FunctionContract(_Frozen):
    id: str
    import_path: str
    execution_class: Literal[
        "stateless",
        "adata_mutation",
        "dataframe_mutation",
        "builder",
        "plot",
    ]
    intent: list[str] = Field(default_factory=list)
    description: str = ""
    parameters: list[Parameter] = Field(default_factory=list)
    requires: list[str] = Field(default_factory=list)
    writes: list[str] = Field(default_factory=list)
    returns_kind: Literal[
        "same_object", "new_object", "value", "none", "plot"
    ] = "value"
    returns_type: str = ""
    next: list[str] = Field(default_factory=list)
    failure_fixes: list[FailureFix] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    tested_on: str = ""
    internal_steps: list[InternalStep] = Field(default_factory=list)
    parameter_sets: list[ParameterSet] = Field(default_factory=list)

    @field_validator("requires", "writes", mode="before")
    @classmethod
    def _canonicalize_state(cls, v: object) -> list[str]:
        return _canonicalize_state(v)


class WorkflowStep(_Frozen):
    call: str
    requires: list[str] = Field(default_factory=list)
    writes: list[str] = Field(default_factory=list)
    args: dict[str, Any] = Field(default_factory=dict)
    optional: bool = False
    description: str = ""

    @field_validator("requires", "writes", mode="before")
    @classmethod
    def _canonicalize_state(cls, v: object) -> list[str]:
        return _canonicalize_state(v)


class WorkflowContract(_Frozen):
    id: str
    description: str
    intent: list[str] = Field(default_factory=list)
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[WorkflowStep] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


# --- Class B: grammar contract --------------------------------------------


class MentalModel(_Frozen):
    for_r_users: str = ""
    for_python_users: str = ""
    general: str = ""


class ConceptSpec(_Frozen):
    id: str
    name: str
    category: str
    description: str
    invariants: list[str] = Field(default_factory=list)
    mental_model: MentalModel
    related_concepts: list[str] = Field(default_factory=list)


class IdiomSpec(_Frozen):
    id: str
    name: str
    applicable_to: list[str] = Field(default_factory=list)
    description: str
    code_template: str
    anti_pattern_paired: str | None = None
    typical_use_case: str = ""


class AntiPatternDetection(_Frozen):
    """How to detect an anti-pattern in user code.

    A detection rule has either an AST-based detector (a callable
    registered via the ``biobabel.detectors`` entry-point group, referred
    to here by ``detector_id``, with structured ``args``) or a plain
    regex, or both. At least one of ``detector_id`` / ``regex`` must be
    set — an empty detection raises at manifest-load time.

    Schema v2: ``ast_pattern`` (the old "kind:arg,arg,..." string) was
    removed; this is the breaking change between v1 and v2.
    """

    detector_id: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    regex: str = ""
    static_only: bool = True

    @model_validator(mode="after")
    def _at_least_one_rule(self) -> AntiPatternDetection:
        if not self.detector_id and not self.regex:
            raise ValueError(
                "AntiPatternDetection: must set at least one of detector_id / regex"
            )
        return self


class AntiPatternSpec(_Frozen):
    id: str
    name: str
    applicable_to: list[str] = Field(default_factory=list)
    detection: AntiPatternDetection
    why_bad: str = ""
    correct_pattern: str | None = None
    code_example_wrong: str = ""
    code_example_right: str = ""


class CompositionSpec(_Frozen):
    id: str
    description: str
    parent: str
    child: str
    constraints: list[str] = Field(default_factory=list)
    typical_errors: list[str] = Field(default_factory=list)


# --- Extension support (ggrepel / patchwork / ggalluvial) -----------------


class ProvidedExtension(_Frozen):
    kind: ExtensionKind
    name: str
    replaces_or_extends: str = ""
    behavior_delta: str = ""
    when_to_use_instead: str = ""


class ExtensionRef(_Frozen):
    pkg: str
    extension_points: list[ExtensionKind] = Field(default_factory=list)
    provides: list[ProvidedExtension] = Field(default_factory=list)


# --- Top-level manifest ---------------------------------------------------


class PackageManifest(_Frozen):
    schema_version: Literal[2] = 2
    repo: str
    distribution: str
    import_name: str
    display_name: str
    contract_class: ContractClass
    tier: int = 3
    type: Literal["overview", "use", "extend", "build-on", "domain"] = "use"
    maturity: Literal["alpha", "beta", "stable"] = "alpha"

    r_package: RPackageRef | None = None
    capabilities: list[str] = Field(default_factory=list)
    domain_tags: list[str] = Field(default_factory=list)
    task_tags: list[str] = Field(default_factory=list)
    foundation: list[str] = Field(default_factory=list)

    triggers: list[TaskTrigger] = Field(default_factory=list)
    not_when: list[str] = Field(default_factory=list)

    # Class A
    functions: list[FunctionContract] = Field(default_factory=list)
    workflows: list[WorkflowContract] = Field(default_factory=list)

    # Class B
    concepts: list[ConceptSpec] = Field(default_factory=list)
    idioms: list[IdiomSpec] = Field(default_factory=list)
    anti_patterns: list[AntiPatternSpec] = Field(default_factory=list)
    compositions: list[CompositionSpec] = Field(default_factory=list)

    # Shared
    recipes: list[Recipe] = Field(default_factory=list)

    # Extension wiring
    extends: list[ExtensionRef] = Field(default_factory=list)
    complements: list[str] = Field(default_factory=list)

    # Provenance
    package_commit: str = ""
    last_verified: str = ""

    @model_validator(mode="after")
    def _class_fields_consistent(self) -> PackageManifest:
        if self.contract_class == "analysis":
            if self.concepts or self.idioms or self.anti_patterns or self.compositions:
                raise ValueError(
                    "contract_class='analysis' must not declare grammar fields "
                    "(concepts/idioms/anti_patterns/compositions). "
                    "Use contract_class='mixed' instead."
                )
        elif self.contract_class == "grammar":
            if self.workflows:
                raise ValueError(
                    "contract_class='grammar' must not declare workflows. "
                    "Use contract_class='mixed' instead."
                )
        return self
