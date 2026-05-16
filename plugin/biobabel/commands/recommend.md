---
description: Recommend a Bio-Babel package for a given analysis or development task.
argument-hint: <task description in natural language>
allowed-tools: mcp__biobabel
---

Call the `biobabel.recommend` MCP tool with `task: "$ARGUMENTS"`.

When the tool returns, present the top recommendation in a compact form:

- **Package**: `<import_name>` (`<distribution>`, `<contract_class>` class)
- **Confidence**: <score>
- **Why**: <rationale>

If the recommendation is a Class A package (analysis state machine), follow up by suggesting `/biobabel:plan $ARGUMENTS` to get the per-step pipeline.

If it's a Class B package (grammar), follow up by calling `biobabel.describe_concept` for the most relevant concept and offering to draft idiomatic code.

If confidence is below 0.3, surface that — it usually means the user's task is outside biobabel's current scope, and you should tell them so rather than push a weak match.
