"""Pydantic model invariants for the manifest API."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from biobabel.manifest_api import (
    AntiPatternDetection,
    FunctionContract,
    PackageManifest,
    WorkflowStep,
)


def _fc(**kw) -> FunctionContract:
    """Minimal FunctionContract with the boilerplate fields filled in."""
    base = {
        "id": "pkg.fn",
        "import_path": "pkg.fn",
        "execution_class": "adata_mutation",
    }
    base.update(kw)
    return FunctionContract(**base)


def test_grammar_must_not_declare_workflows():
    with pytest.raises(ValidationError, match="must not declare workflows"):
        PackageManifest(
            repo="x",
            distribution="x",
            import_name="x",
            display_name="x",
            contract_class="grammar",
            workflows=[{"id": "wf", "description": "x"}],  # type: ignore[arg-type]
        )


def test_analysis_must_not_declare_grammar_fields():
    with pytest.raises(ValidationError, match="must not declare grammar fields"):
        PackageManifest(
            repo="x",
            distribution="x",
            import_name="x",
            display_name="x",
            contract_class="analysis",
            concepts=[
                {
                    "id": "c",
                    "name": "C",
                    "category": "x",
                    "description": "",
                    "mental_model": {"general": ""},
                }
            ],  # type: ignore[arg-type]
        )


def test_anti_pattern_detection_requires_at_least_one_rule():
    with pytest.raises(ValidationError, match="at least one of"):
        AntiPatternDetection()


def test_anti_pattern_detection_accepts_detector_id():
    d = AntiPatternDetection(detector_id="rgrid.for_loop_calls", args={"calls": ["x"]})
    assert d.detector_id == "rgrid.for_loop_calls"
    assert d.args == {"calls": ["x"]}


def test_anti_pattern_detection_accepts_regex_only():
    d = AntiPatternDetection(regex=r"foo")
    assert d.regex == "foo"
    assert d.detector_id == ""


def test_anti_pattern_detection_rejects_legacy_ast_pattern_field():
    """v1 used ``ast_pattern: "kind:arg"``. v2 dropped that field; a stale
    YAML still carrying it must fail loudly under Pydantic's extra=forbid."""
    with pytest.raises(ValidationError, match="ast_pattern"):
        AntiPatternDetection(ast_pattern="for_loop_calls:foo")  # type: ignore[call-arg]


def test_package_manifest_rejects_unsupported_schema_version():
    """Any non-2 schema_version must fail loudly. The field is Literal[2],
    so a YAML still declaring ``schema_version: 1`` (or a typo'd 99) does
    not silently load with a misleading version number — it raises."""
    base = {
        "repo": "x",
        "distribution": "x",
        "import_name": "x",
        "display_name": "x",
        "contract_class": "grammar",
        "concepts": [
            {
                "id": "x.c",
                "name": "C",
                "category": "x",
                "description": "",
                "mental_model": {"general": ""},
            }
        ],
    }
    for bad in (1, 3, 99):
        with pytest.raises(ValidationError, match="schema_version"):
            PackageManifest(schema_version=bad, **base)


# --- requires / writes canonicalization ------------------------------------


def test_requires_accepts_canonical_flat_list():
    fn = _fc(requires=["obs.Size_Factor", "obsm.X_pca", "X:raw_counts"])
    assert fn.requires == ["obs.Size_Factor", "obsm.X_pca", "X:raw_counts"]


def test_writes_accepts_empty_inputs():
    """Both ``{}`` (legacy dict default) and ``[]`` (canonical default) normalize to ``[]``."""
    assert _fc(writes={}).writes == []
    assert _fc(writes=[]).writes == []
    assert _fc().writes == []


def test_requires_absorbs_legacy_adata_container():
    fn = _fc(requires={"adata": {"X": "raw_counts", "obs": ["Size_Factor"]}})
    assert fn.requires == ["X:raw_counts", "obs.Size_Factor"]


def test_requires_absorbs_multi_container_query_ref_adata():
    """monocle3 label-transfer functions use both ``query_adata`` and
    ``ref_adata`` simultaneously; the absorber merges and dedupes them."""
    fn = _fc(
        requires={
            "query_adata": {"obsm": ["X_umap"]},
            "ref_adata": {"obsm": ["X_umap"]},
        }
    )
    assert fn.requires == ["obsm.X_umap"]


def test_requires_rejects_unknown_slot():
    with pytest.raises(ValidationError, match="unknown slot 'oops'"):
        _fc(requires=["oops.foo"])


def test_requires_rejects_unknown_x_semantic():
    with pytest.raises(ValidationError, match="unknown X semantic"):
        _fc(requires=["X:bogus"])


def test_requires_rejects_token_without_separator():
    with pytest.raises(ValidationError, match="must be '<slot>.<key>' or 'X:<semantic>'"):
        _fc(requires=["just_a_word"])


def test_requires_rejects_legacy_dict_with_unknown_inner_key():
    with pytest.raises(ValidationError, match="unknown inner key 'mystery'"):
        _fc(requires={"adata": {"mystery": ["foo"]}})


def test_requires_rejects_legacy_dict_with_non_dict_container():
    with pytest.raises(ValidationError, match="must wrap a dict"):
        _fc(requires={"adata": "not a dict"})


def test_requires_rejects_non_string_non_dict():
    with pytest.raises(ValidationError, match="must be a list of strings or a legacy nested dict"):
        _fc(requires=42)  # type: ignore[arg-type]


def test_workflow_step_validates_tokens_too():
    """WorkflowStep was already ``list[str]`` but now also enforces token grammar."""
    step = WorkflowStep(call="x.fn", requires=["obs.Size_Factor"], writes=["obsm.X_pca"])
    assert step.requires == ["obs.Size_Factor"]
    with pytest.raises(ValidationError, match="unknown slot 'foo'"):
        WorkflowStep(call="x.fn", requires=["foo.bar"])


def test_json_schema_round_trip():
    schema = PackageManifest.model_json_schema()
    assert schema["title"] == "PackageManifest"
    # core fields present
    properties = schema["properties"]
    for name in ("contract_class", "concepts", "functions", "recipes"):
        assert name in properties
