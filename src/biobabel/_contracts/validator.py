"""Validate `_biobabel/` directory: mandatory-file matrix + manifest schema.

Per §3.4:

    | file                          | Class A | Class B | Mixed |
    | pyproject [tool.biobabel]+ep  |    ✓    |    ✓    |   ✓   |
    | package.yaml                  |    ✓    |    ✓    |   ✓   |
    | skill.md                      |    ✓    |    ✓    |   ✓   |
    | examples/smoke.py             |    ✓    |    ✓    |   ✓   |
    | recipes/ (>=1)                |    ✓    |    ✓    |   ✓   |
    | functions/                    |    ✓    |    -    |   ✓   |
    | workflows/                    |    ✓    |    -    | opt   |
    | concepts/                     |    -    |    ✓    |   ✓   |
    | idioms/                       |    -    |    ✓    |   ✓   |
    | anti_patterns/                |    -    |    ✓    |   ✓   |
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml
from pydantic import ValidationError

from biobabel.manifest_api import PackageManifest

Severity = Literal["error", "warning", "info"]


@dataclass
class ContractIssue:
    severity: Severity
    code: str
    message: str
    path: str = ""


@dataclass
class ContractValidationReport:
    ok: bool
    package_dir: Path
    contract_class: str | None = None
    manifest: PackageManifest | None = None
    issues: list[ContractIssue] = field(default_factory=list)

    def errors(self) -> list[ContractIssue]:
        return [i for i in self.issues if i.severity == "error"]

    def warnings(self) -> list[ContractIssue]:
        return [i for i in self.issues if i.severity == "warning"]


def validate_manifest_only(manifest: PackageManifest) -> list[ContractIssue]:
    """Schema-only validation against a constructed manifest (no file system)."""
    issues: list[ContractIssue] = []

    if manifest.contract_class == "analysis" and not manifest.functions:
        issues.append(
            ContractIssue(
                severity="error",
                code="missing_functions",
                message="Class A 'analysis' manifest must declare at least one FunctionContract.",
            )
        )

    if manifest.contract_class == "grammar":
        if not manifest.concepts:
            issues.append(
                ContractIssue(
                    severity="error",
                    code="missing_concepts",
                    message="Class B 'grammar' manifest must declare at least one ConceptSpec.",
                )
            )
        if not manifest.idioms:
            issues.append(
                ContractIssue(
                    severity="warning",
                    code="missing_idioms",
                    message="Class B 'grammar' manifest declares no idioms; agent-as-developer needs them.",
                )
            )

    if manifest.contract_class == "mixed":
        if not manifest.functions:
            issues.append(
                ContractIssue(
                    severity="error",
                    code="missing_functions",
                    message="Class AB 'mixed' manifest must declare functions.",
                )
            )
        if not manifest.concepts:
            issues.append(
                ContractIssue(
                    severity="error",
                    code="missing_concepts",
                    message="Class AB 'mixed' manifest must declare concepts.",
                )
            )

    if not manifest.recipes:
        issues.append(
            ContractIssue(
                severity="error",
                code="missing_recipes",
                message="At least one recipe is mandatory.",
            )
        )

    return issues


def validate_package_dir(biobabel_dir: Path) -> ContractValidationReport:
    """Walk an upstream package's `_biobabel/` directory and validate everything."""
    biobabel_dir = biobabel_dir.resolve()

    if not biobabel_dir.is_dir():
        return ContractValidationReport(
            ok=False,
            package_dir=biobabel_dir,
            issues=[
                ContractIssue(
                    severity="error",
                    code="dir_missing",
                    message=f"_biobabel directory not found at {biobabel_dir}",
                )
            ],
        )

    issues: list[ContractIssue] = []

    # 1. package.yaml mandatory
    pkg_yaml = biobabel_dir / "package.yaml"
    if not pkg_yaml.is_file():
        return ContractValidationReport(
            ok=False,
            package_dir=biobabel_dir,
            issues=[
                ContractIssue(
                    severity="error",
                    code="missing_package_yaml",
                    message="package.yaml is mandatory; cannot determine contract_class.",
                    path=str(pkg_yaml),
                )
            ],
        )

    # 2. load + parse
    try:
        raw = yaml.safe_load(pkg_yaml.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return ContractValidationReport(
            ok=False,
            package_dir=biobabel_dir,
            issues=[
                ContractIssue(
                    severity="error",
                    code="package_yaml_unparseable",
                    message=f"package.yaml YAML parse error: {exc}",
                    path=str(pkg_yaml),
                )
            ],
        )

    # 3. inline class-specific yaml files (functions/, concepts/, ...)
    raw = _hydrate_dir_files(raw, biobabel_dir)

    # 4. schema-validate
    try:
        manifest = PackageManifest.model_validate(raw)
    except ValidationError as exc:
        return ContractValidationReport(
            ok=False,
            package_dir=biobabel_dir,
            issues=[
                ContractIssue(
                    severity="error",
                    code="schema_invalid",
                    message=str(exc),
                    path=str(pkg_yaml),
                )
            ],
        )

    issues.extend(validate_manifest_only(manifest))

    # 5. common mandatory files
    issues.extend(_check_mandatory_files(biobabel_dir, manifest.contract_class))

    # 6. recipe files exist
    for recipe in manifest.recipes:
        recipe_path = (biobabel_dir / recipe.path).resolve()
        if not recipe_path.is_file():
            issues.append(
                ContractIssue(
                    severity="error",
                    code="recipe_file_missing",
                    message=f"Recipe '{recipe.id}' declares path '{recipe.path}' but file is missing.",
                    path=str(recipe_path),
                )
            )

    has_errors = any(i.severity == "error" for i in issues)
    return ContractValidationReport(
        ok=not has_errors,
        package_dir=biobabel_dir,
        contract_class=manifest.contract_class,
        manifest=manifest,
        issues=issues,
    )


def _check_mandatory_files(biobabel_dir: Path, contract_class: str) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    common = {
        "skill.md": "file",
        "examples/smoke.py": "file",
        "recipes": "dir",
    }
    for rel, kind in common.items():
        p = biobabel_dir / rel
        ok = p.is_file() if kind == "file" else p.is_dir()
        if not ok:
            issues.append(
                ContractIssue(
                    severity="error",
                    code=f"missing_{rel.replace('/', '_').replace('.', '_')}",
                    message=f"Mandatory {kind} '{rel}' is missing.",
                    path=str(p),
                )
            )

    if biobabel_dir.joinpath("recipes").is_dir():
        recipe_files = list(biobabel_dir.joinpath("recipes").glob("*.py"))
        if not recipe_files:
            issues.append(
                ContractIssue(
                    severity="error",
                    code="recipes_dir_empty",
                    message="recipes/ directory exists but contains no *.py recipes.",
                    path=str(biobabel_dir / "recipes"),
                )
            )

    class_required: dict[str, list[str]] = {
        "analysis": ["functions"],
        "grammar": ["concepts", "idioms", "anti_patterns"],
        "mixed": ["functions", "concepts", "idioms", "anti_patterns"],
    }
    for sub in class_required.get(contract_class, []):
        sub_dir = biobabel_dir / sub
        if not sub_dir.is_dir() or not list(sub_dir.glob("*.yaml")):
            issues.append(
                ContractIssue(
                    severity="error",
                    code=f"missing_{sub}",
                    message=f"contract_class='{contract_class}' requires non-empty {sub}/ directory.",
                    path=str(sub_dir),
                )
            )
    return issues


_DIR_FIELD_MAP = {
    "functions": "functions",
    "workflows": "workflows",
    "concepts": "concepts",
    "idioms": "idioms",
    "anti_patterns": "anti_patterns",
    "compositions": "compositions",
}


def _hydrate_dir_files(raw: dict, biobabel_dir: Path) -> dict:
    """Merge per-class subdir YAML files into the manifest dict.

    Each `<dir>/*.yaml` is loaded and appended to the corresponding list field
    on the manifest. If a field is already populated inline in package.yaml,
    sub-directory files are appended to it.
    """
    for subdir, field_name in _DIR_FIELD_MAP.items():
        sub_path = biobabel_dir / subdir
        if not sub_path.is_dir():
            continue
        items: list[dict] = list(raw.get(field_name, []) or [])
        for yaml_file in sorted(sub_path.glob("*.yaml")):
            loaded = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
            if loaded is None:
                continue
            if isinstance(loaded, list):
                items.extend(loaded)
            else:
                items.append(loaded)
        if items:
            raw[field_name] = items

    return raw
