#!/usr/bin/env python3
"""Codex UserPromptSubmit hook: detect R-style syntax in the user's prompt.

Codex variant of the Claude Code hook. The detection logic is identical; the
*I/O contract is Codex's*, which differs from Claude Code:

    input  (stdin JSON):  {"prompt": "<text>", "hook_event_name": "UserPromptSubmit", ...}
    output (stdout JSON):  {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                   "additionalContext": "<advice>"}}

(Claude Code instead reads ``{"prompt": ...}`` and emits
``{"decision": "allow", "context": ...}`` — see plugin/biobabel/hooks/.)

The natural failure mode of an LLM when the user pastes R code into chat is
line-by-line guess-translation. The Python port of a Bio-Babel package may NOT
mirror R 1:1. This hook injects context telling the agent to look up the
authoritative Python contract via biobabel's MCP tools instead of guessing.

Exits 0 with no output if nothing matched.
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
        "`cds <- ...` looks like a Monocle CellDataSet assignment. The Python analog usually uses `AnnData`. Search `biobabel.search_contracts(query='pseudotime trajectory')`, then inspect matching workflows and symbols before writing code.",
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

    seen: set[str] = set()
    unique_hints: list[str] = []
    for pattern, hint in R_INDICATORS:
        if pattern.search(prompt) and hint not in seen:
            seen.add(hint)
            unique_hints.append(hint)

    if not unique_hints:
        return 0

    context_lines = [
        "biobabel: detected R-style syntax in the user's prompt. "
        "Do NOT guess a Python translation line-by-line — the Python port may not "
        "mirror R 1:1. Look up the authoritative Python API via "
        "biobabel.describe_concept / describe_symbol / list_idioms instead. Hints:",
    ]
    context_lines.extend(f"  - {hint}" for hint in unique_hints)

    response = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "\n".join(context_lines),
        }
    }
    json.dump(response, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
