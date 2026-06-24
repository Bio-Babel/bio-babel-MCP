---
name: biobabel-overview
description: 12 read-only MCP tools for Bio-Babel — discover exact package contracts and validate snippets. Read this first when the user mentions an R bioinformatics package or a Bio-Babel name.
biobabel_version: 0.3.0
---

# biobabel

Bio-Babel's read-only contract layer surfaces schema-v1 packages installed in the current environment. Call `biobabel.list_packages()` for the live registry; this shipped skill does not assume which producer packages are installed.

## Decision tree

Pick the route by what the user is doing:

| User says                                                        | Reach for                                            |
|------------------------------------------------------------------|------------------------------------------------------|
| "run pseudotime / trajectory / monocle2py / monocle3 / clustering" | `biobabel.list_packages` / `list_symbols` → `biobabel.list_workflows` / `describe_workflow` → `describe_symbol` for exact calls |
| "draw / plot / custom geom / grid / ggplot2 / pheatmap"          | `biobabel.list_symbols` → `biobabel.describe_symbol` + `describe_concept` + `list_idioms` |
| pastes R syntax (`library(`, `<-`, `%>%`)                        | look up the Python contract with `describe_symbol` / `describe_concept` / `list_idioms` |
| "add biobabel support to my package"                             | use the maintainer CLI: `biobabel new contract --pkg <import_name>` |
| review a Bio-Babel R-port PR                                     | inspect `_biobabel/` contracts and run the package tests directly |

## Hard rules

1. Never echo R syntax as Python. Look up the Python-side contract instead of translating line-by-line.
2. The agent owns intent understanding and planning. biobabel only returns exact package facts and reference workflows.
3. Before using an unfamiliar workflow step, call `biobabel.describe_symbol` for the exact signature, parameters, writes, and failure fixes.
4. Run `biobabel.check_code` on non-trivial snippets before showing or executing them — it is a static AST lint and never runs the code.
5. biobabel never executes code — it is a read-only contract layer. Run snippets with your own tools (terminal / python).

## Discovering more

- `biobabel.list_packages()` — registry snapshot (plus any discovery errors)
- `biobabel.describe_package(import_name=X)` — the full manifest for one package
- `biobabel.list_workflows(package=X)` / `biobabel.describe_workflow(workflow_id=...)` — reference workflows
- `biobabel.list_symbols(package=X, query=...)` / `biobabel.describe_symbol(symbol_id=...)` — search + read exact callable contracts
- `biobabel.list_templates(package=X)` / `biobabel.describe_template(template_id=...)` — reusable code skeletons
- `biobabel.describe_concept(concept_id=...)` — Class B mental models
- `biobabel.list_idioms(package=X)` / `biobabel.describe_idiom(idiom_id=...)` — Class B grammar patterns
- `biobabel.check_code(code=..., package=X)` — static AST policy + anti-pattern lint
