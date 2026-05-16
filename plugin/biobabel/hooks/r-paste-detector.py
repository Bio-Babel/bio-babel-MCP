#!/usr/bin/env python3
"""UserPromptSubmit hook: detect R-style syntax in the user's prompt.

The natural failure mode of an LLM when the user pastes R code into chat is
*line-by-line guess-translation*. The Python port of a Bio-Babel package may
NOT mirror R 1:1 — `aes(x, y)` becomes `aes(x='x', y='y')`, `facet_wrap(~ x)`
becomes `facet_wrap('x')`, `<-` is `=`, `library(...)` has no equivalent.

This hook intercepts before the LLM sees the prompt and injects context
telling the agent to **look up the Python API directly** via
`biobabel.describe_concept` / `biobabel.describe_symbol` / `biobabel.list_idioms`
rather than guess from R syntax.

This is NOT an R-to-Python translator. There is no such tool in biobabel by
design (see ADR-0005). The hook redirects the agent toward the authoritative
Python contract — which is all that matters for correctness.

Reads JSON on stdin:
    {"prompt": "<text>", ...}

Writes JSON on stdout if R syntax is detected:
    {"decision": "allow", "context": "<advice>"}

Exits 0 silently if nothing matched.
"""

from __future__ import annotations

import json
import re
import sys

R_INDICATORS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\blibrary\s*\([^)]+\)"),
        "`library(...)` is R's import; in Python you `pip install` the corresponding Bio-Babel package and `import` it. No translation needed.",
    ),
    (
        re.compile(r"\brequire\s*\([^)]+\)"),
        "`require(...)` is R's conditional import; no Python equivalent — just `import`.",
    ),
    (
        re.compile(r"(?<![<=!])<-(?!-)"),
        "`<-` is R's assignment; Python uses `=`.",
    ),
    (
        re.compile(r"%>%"),
        "magrittr pipe `%>%` has no direct Python equivalent — chain method calls or use a temp variable.",
    ),
    (
        re.compile(r"\baes\s*\([^)=]+,\s*[^)=]+\)"),
        "ggplot2 `aes(x, y)` requires keyword args + string column names in Python: `aes(x='x', y='y')`. Call `biobabel.describe_symbol(symbol_id='ggplot2_py.aes')` for the authoritative signature.",
    ),
    (
        re.compile(r"\bgg(?:plot|repel|alluvial)\s*\("),
        "ggplot2-family call detected. Python ports: `ggplot2_py` / `ggrepel_py` / `ggalluvial_py`. Use `biobabel.describe_symbol(symbol_id='ggplot2_py.<name>')` + `biobabel.list_idioms(package='ggplot2_py')` for the correct Python API.",
    ),
    (
        re.compile(r"\bcds\s*<-"),
        "`cds <- ...` looks like a Monocle3 CellDataSet assignment. The Python analog uses `AnnData`. Call `biobabel.plan_workflow(task='pseudotime trajectory')` for the canonical 6-step pipeline.",
    ),
    (
        re.compile(r"\bpushViewport\s*\(|\bpopViewport\s*\(|\bgrid\.[A-Za-z]+\s*\("),
        "R `grid` syntax detected. The Python port is `grid_py` with `push_viewport` / `pop_viewport` / `grid_rect` etc. Call `biobabel.describe_concept(concept_id='grid_py.Viewport')` and `biobabel.list_idioms(package='grid_py')` for the authoritative Python API.",
    ),
]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    prompt = payload.get("prompt", "") or payload.get("user_input", "")
    if not isinstance(prompt, str) or not prompt:
        return 0

    matches: list[str] = []
    for pattern, hint in R_INDICATORS:
        if pattern.search(prompt):
            matches.append(hint)

    if not matches:
        return 0

    # Dedupe while preserving order.
    seen: set[str] = set()
    unique_hints: list[str] = []
    for hint in matches:
        if hint not in seen:
            seen.add(hint)
            unique_hints.append(hint)

    context_lines = [
        "biobabel: detected R-style syntax in the user's prompt. "
        "Do NOT guess a Python translation line-by-line — the Python port may not "
        "mirror R 1:1. Look up the authoritative Python API via "
        "biobabel.describe_concept / describe_symbol / list_idioms instead. Hints:",
    ]
    for hint in unique_hints:
        context_lines.append(f"  - {hint}")

    response = {
        "decision": "allow",
        "context": "\n".join(context_lines),
    }
    json.dump(response, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
