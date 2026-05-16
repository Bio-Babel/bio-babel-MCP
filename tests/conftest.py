"""Shared pytest fixtures: a synthetic Registry that doesn't need installed pkgs."""

from __future__ import annotations

import pytest

from biobabel._registry.builder import Registry
from biobabel._registry.discovery import DiscoveredManifest
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
                    ast_pattern="for_loop_calls:rect_grob,text_grob",
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
                    ast_pattern="unbalanced:push_viewport,pop_viewport",
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
        distribution_version="4.5.3.post3",
        manifest=grammar_manifest,
    )
    reg.packages["monocle3_py"] = DiscoveredManifest(
        import_name="monocle3_py",
        distribution="monocle3-python",
        distribution_version="0.1.0",
        manifest=analysis_manifest,
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
