"""Pydantic model invariants for the manifest API."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from biobabel.manifest_api import (
    AntiPatternDetection,
    PackageManifest,
)


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


def test_json_schema_round_trip():
    schema = PackageManifest.model_json_schema()
    assert schema["title"] == "PackageManifest"
    # core fields present
    properties = schema["properties"]
    for name in ("contract_class", "concepts", "functions", "recipes"):
        assert name in properties
