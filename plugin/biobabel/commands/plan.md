---
description: Plan a full pipeline (WorkflowContract or ad-hoc DAG) for an agent-as-user task.
argument-hint: <task description, e.g. "pseudotime trajectory on PBMC3k">
allowed-tools: mcp__biobabel
---

Call `biobabel.plan_workflow` with `task: "$ARGUMENTS"`.

Render the result as a numbered list. For each step:

```
N. <call>
   requires: <slot list>
   writes:   <slot list>
```

If `source == "workflow_contract"`, prefix the list with: *"Matched known workflow `<workflow_id>`."*

If `source == "adhoc_bfs"`, prefix with: *"Assembled via BFS — review carefully before running."*

After listing the steps, offer the user three concrete next moves:
1. `biobabel.create_session` + `biobabel.load_adata` to start running, **or**
2. `biobabel.describe_symbol` on any step to see its full state-graph contract, **or**
3. `biobabel.check_prerequisites` against a loaded adata to verify step 1 is satisfied before calling it.
