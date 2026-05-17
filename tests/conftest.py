"""Shared pytest fixtures: a synthetic Registry that doesn't need installed pkgs.

The registry fixture mirrors what ``build_registry()`` would assemble under
schema v2: it loads two manifests (one grammar, one analysis) and attaches a
small set of in-process detectors so anti-pattern tests can run without
going through entry-point discovery.
"""

from __future__ import annotations

import ast
from typing import Any

import pytest

from biobabel._registry.builder import Registry
from biobabel._registry.discovery import DiscoveredDetector, DiscoveredManifest
from biobabel.detector_api import DetectorMatch
from biobabel.manifest_api import (
    AntiPatternDetection,
    AntiPatternSpec,
    ConceptSpec,
    FunctionContract,
    IdiomSpec,
    MentalModel,
    PackageManifest,
    Recipe,
    TaskTrigger,
    WorkflowContract,
    WorkflowStep,
)


# --- In-process detectors used by the grammar manifest's anti_patterns ----
#
# In real deployments these would live in rgrid-python's _biobabel/detectors.py
# and be discovered via entry-points. For tests we wire them directly so the
# fixture is self-contained and does not depend on the upstream package being
# pip-installed.


def _fake_for_loop_calls(tree: ast.AST, args: dict[str, Any]) -> list[DetectorMatch]:
    targets = set(args.get("calls", []))
    hits: list[DetectorMatch] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.AsyncFor)):
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    fn = child.func
                    name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
                    if name in targets:
                        hits.append(DetectorMatch(line=node.lineno, detail={"target_call": name}))
                        break
    return hits


def _fake_unbalanced(tree: ast.AST, args: dict[str, Any]) -> list[DetectorMatch]:
    push_fn = args.get("push", "")
    pop_fn = args.get("pop", "")
    push_count = pop_count = 0
    first_line = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
            if name == push_fn:
                push_count += 1
                if not first_line:
                    first_line = node.lineno
            elif name == pop_fn:
                pop_count += 1
    if push_count != pop_count:
        return [DetectorMatch(line=first_line or 1, detail={"push": push_count, "pop": pop_count})]
    return []


@pytest.fixture
def grammar_manifest() -> PackageManifest:
    return PackageManifest(
        repo="https://github.com/Bio-Babel/rgrid-python",
        distribution="rgrid-python",
        import_name="grid_py",
        display_name="grid_py",
        contract_class="grammar",
        tier=1,
        type="build-on",
        maturity="beta",
        capabilities=["viewport-stack", "grob-tree"],
        task_tags=["new-plotting-package", "sub-region-drawing"],
        triggers=[
            TaskTrigger(intent="build a plotting package on top of grid", confidence=0.95),
        ],
        concepts=[
            ConceptSpec(
                id="grid_py.Viewport",
                name="Viewport",
                category="drawing-context",
                description="Rectangular region on a graphics device.",
                invariants=["push and pop must balance"],
                mental_model=MentalModel(general="stack of coordinate transforms"),
            ),
        ],
        idioms=[
            IdiomSpec(
                id="grid_py.push_draw_pop",
                name="Push-Draw-Pop",
                applicable_to=["grid_py.Viewport"],
                description="Standard sub-region drawing.",
                code_template="push_viewport(...); grid_rect(); pop_viewport()",
            ),
        ],
        anti_patterns=[
            AntiPatternSpec(
                id="grid_py.grob_in_loop",
                name="Building grobs in a loop",
                applicable_to=["grid_py.Grob"],
                detection=AntiPatternDetection(
                    detector_id="rgrid.for_loop_calls",
                    args={"calls": ["rect_grob", "text_grob"]},
                ),
                why_bad="N draws instead of 1.",
                correct_pattern="grid_py.build_grobtree",
                code_example_right="grid_draw(grob_tree(*rects))",
            ),
            AntiPatternSpec(
                id="grid_py.unbalanced_push_pop",
                name="Unbalanced push_pop",
                applicable_to=["grid_py.Viewport"],
                detection=AntiPatternDetection(
                    detector_id="rgrid.unbalanced",
                    args={"push": "push_viewport", "pop": "pop_viewport"},
                ),
                why_bad="Stack ends dirty.",
                correct_pattern="grid_py.try_finally_pop",
            ),
        ],
        recipes=[
            Recipe(
                id="grid_py.basic_subplot",
                path="recipes/basic_subplot.py",
                description="Basic subplot",
            ),
        ],
    )


@pytest.fixture
def analysis_manifest() -> PackageManifest:
    return PackageManifest(
        repo="https://github.com/Bio-Babel/Monocle3-python",
        distribution="monocle3-python",
        import_name="monocle3_py",
        display_name="monocle3",
        contract_class="analysis",
        tier=2,
        type="domain",
        maturity="beta",
        task_tags=["pseudotime", "trajectory"],
        triggers=[TaskTrigger(intent="pseudotime trajectory")],
        functions=[
            FunctionContract(
                id="monocle3.estimate_size_factors",
                import_path="monocle3.estimate_size_factors",
                execution_class="adata_mutation",
                intent=["pseudotime trajectory"],
                description="Compute per-cell size factors.",
                writes={"adata": {"obs": ["Size_Factor"]}},
                next=["monocle3.preprocess_cds"],
            ),
            FunctionContract(
                id="monocle3.preprocess_cds",
                import_path="monocle3.preprocess_cds",
                execution_class="adata_mutation",
                intent=["pseudotime trajectory"],
                requires={"adata": {"obs": ["Size_Factor"]}},
                writes={"adata": {"obsm": ["X_pca"]}},
                next=["monocle3.reduce_dimension"],
            ),
            FunctionContract(
                id="monocle3.reduce_dimension",
                import_path="monocle3.reduce_dimension",
                execution_class="adata_mutation",
                intent=["pseudotime trajectory"],
                requires={"adata": {"obsm": ["X_pca"]}},
                writes={"adata": {"obsm": ["X_umap"]}},
            ),
        ],
        workflows=[
            WorkflowContract(
                id="monocle3.basic_trajectory",
                description="Basic pseudotime trajectory.",
                intent=["pseudotime trajectory"],
                steps=[
                    WorkflowStep(call="monocle3.estimate_size_factors", writes=["obs.Size_Factor"]),
                    WorkflowStep(
                        call="monocle3.preprocess_cds",
                        requires=["obs.Size_Factor"],
                        writes=["obsm.X_pca"],
                    ),
                ],
            )
        ],
        recipes=[Recipe(id="monocle3.basic", path="recipes/basic.py")],
    )


@pytest.fixture
def registry(grammar_manifest, analysis_manifest) -> Registry:
    reg = Registry()
    reg.packages["grid_py"] = DiscoveredManifest(
        import_name="grid_py",
        distribution="rgrid-python",
        distribution_version="4.5.3.post4",
        manifest=grammar_manifest,
    )
    reg.packages["monocle3_py"] = DiscoveredManifest(
        import_name="monocle3_py",
        distribution="monocle3-python",
        distribution_version="0.1.0",
        manifest=analysis_manifest,
    )

    # Detectors that the grammar manifest's anti_patterns reference.
    for did, fn in (
        ("rgrid.for_loop_calls", _fake_for_loop_calls),
        ("rgrid.unbalanced", _fake_unbalanced),
    ):
        reg.detectors[did] = DiscoveredDetector(
            detector_id=did,
            distribution="rgrid-python",
            distribution_version="4.5.3.post4",
            fn=fn,
        )

    for d in reg.packages.values():
        m = d.manifest
        for fn in m.functions:
            reg._function_by_id[fn.id] = (d.import_name, fn)
        for wf in m.workflows:
            reg._workflow_by_id[wf.id] = (d.import_name, wf)
        for c in m.concepts:
            reg._concept_by_id[c.id] = (d.import_name, c)
        for i in m.idioms:
            reg._idiom_by_id[i.id] = (d.import_name, i)
        for ap in m.anti_patterns:
            reg._anti_pattern_by_id[ap.id] = (d.import_name, ap)
    return reg
