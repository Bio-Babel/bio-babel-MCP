---
name: biobabel-overview
description: 20 MCP tools for Bio-Babel — discover, plan, validate, and run registered Bio-Babel packages. Read this first when the user mentions an R bioinformatics package or a Bio-Babel name.
biobabel_version: 0.2.0
---

# biobabel

Bio-Babel's agent control plane currently surfaces **6** package(s):

- **Class analysis**: monocle2py, monocle3
- **Class grammar**: grid_py, gtable_py, scales
- **Class mixed**: ggplot2_py

## Decision tree

Pick the route by what the user is doing:

| User says                                                        | Reach for                                            |
|------------------------------------------------------------------|------------------------------------------------------|
| "run pseudotime / trajectory / monocle3 / copykat / clustering"  | `biobabel.list_packages` (read triggers/tags, pick the Class A package) → `biobabel.plan_workflow` |
| "draw / plot / custom geom / grid / ggplot2 / pheatmap"          | `biobabel.list_packages` (read triggers/tags, pick the Class B package) → `biobabel.describe_concept` + `list_idioms` |
| pastes R syntax (`library(`, `<-`, `%>%`)                        | look up the Python contract with `describe_symbol` / `describe_concept` / `list_idioms` |
| "add biobabel support to my package"                             | use the maintainer CLI: `biobabel new contract --pkg <import_name>` |
| review a Bio-Babel R-port PR                                     | inspect `_biobabel/` contracts and run the package tests directly |

## Hard rules

1. Never echo R syntax as Python. Look up the Python-side contract instead of translating line-by-line.
2. For Class A packages, run `biobabel.check_prerequisites` before any step that requires upstream state.
3. For Class B packages, run `biobabel.check_code` on any non-trivial snippet before showing it to the user — anti-pattern detection catches the cardinal footguns.
4. `biobabel.run_code` runs in a guarded subprocess; it catches common agent mistakes but is not a security boundary.
5. After runtime failures or confusing multi-step state, call `biobabel.list_traces()` to inspect recent runtime calls in the default session.

## Discovering more

- `biobabel.list_packages()` — registry snapshot
- `biobabel.list_tools()` — full MCP tool list
- `biobabel.list_idioms(package=X)` — Class B grammar patterns
- `biobabel.health()` — discovery errors + session state
- `biobabel.list_traces()` — recent runtime calls, handle refs, artifact refs, and code hashes
