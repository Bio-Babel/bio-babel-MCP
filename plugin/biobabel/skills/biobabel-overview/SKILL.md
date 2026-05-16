---
name: biobabel-overview
description: 27 MCP tools for Bio-Babel — discover, plan, translate, retrofit. Read this first when the user mentions an R bioinformatics package or a Bio-Babel name.
biobabel_version: 0.1.0
---

# biobabel

Bio-Babel's agent control plane currently surfaces **5** package(s):

- **Class analysis**: monocle3
- **Class grammar**: grid_py, gtable_py, scales
- **Class mixed**: ggplot2_py

## Decision tree

Pick the route by what the user is doing:

| User says                                                        | Reach for                                            |
|------------------------------------------------------------------|------------------------------------------------------|
| "run pseudotime / trajectory / monocle3 / copykat / clustering"  | `biobabel.recommend` → `biobabel.plan_workflow` (Class A) |
| "draw / plot / custom geom / grid / ggplot2 / pheatmap"          | `biobabel.recommend` → `biobabel.describe_concept` + `list_idioms` (Class B) |
| pastes R syntax (`library(`, `<-`, `%>%`)                        | `/biobabel:r-translate <snippet>`                    |
| pastes a whole .R script                                         | `/biobabel:migrate <path>`                           |
| "add biobabel support to my package"                             | invoke the **contract-retrofitter** subagent         |
| review a Bio-Babel R-port PR                                     | invoke the **r-parity-auditor** subagent             |

## Hard rules

1. Never echo R syntax as Python. Translate via `biobabel.r_translate`.
2. For Class A packages, run `biobabel.check_prerequisites` before any step that requires upstream state.
3. For Class B packages, run `biobabel.check_code` on any non-trivial snippet before showing it to the user — anti-pattern detection catches the cardinal footguns.
4. `biobabel.run_code` is sandboxed; you can call it without risk to the user's workspace.

## Discovering more

- `biobabel.list_packages()` — registry snapshot
- `biobabel.list_tools()` — full MCP tool list
- `biobabel.list_idioms(package=X)` — Class B grammar patterns
- `biobabel.health()` — discovery errors + session state
