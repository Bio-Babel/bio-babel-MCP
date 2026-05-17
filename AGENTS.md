# AGENTS.md — guidance for AI agents working in this repo

This file is loaded by Claude Code / Cursor / Codex / Continue / etc. when working *inside* the `biobabel` repository itself.

(Note: `biobabel` is the agent control plane *for downstream Bio-Babel packages*. When an agent uses `biobabel` from a user's project, the relevant guidance is shipped via the Claude Code plugin's skills, not via this file.)

## Hard rules

1. **No reflection fallback.** `biobabel` only sees upstream packages that ship a `_biobabel/` contract directory. There is no inspection-based degraded mode. Tests assert this; do not weaken.
2. **No legacy / no backward-compat shims.** This is a fresh repo (not a continuation of `bio-babel-harness`). Do not add `_legacy/`, `aibio.*`, or `bio-babel-harness` aliases.
3. **Contract is mandatory.** Per the validation matrix in `docs/contract-matrix.md`, missing required files → package unregistered. Do not add "partial" or "degraded" modes.
4. **MCP first.** All agent-facing functionality must be reachable through an MCP tool. CLI exists for human maintainers, not agents.

## Code conventions

- Python 3.12+, `from __future__ import annotations` everywhere.
- Pydantic v2 for all schemas. Models live in `src/biobabel/manifest_api.py` and are re-exported.
- Internal-only modules are prefixed `_` (`_registry/`, `_runtime/`, ...). Two public Python surfaces: `biobabel.manifest_api` (contract schemas) and `biobabel.detector_api` (AST detector types — `DetectorMatch`, `DetectorFn`). Adding a third public surface requires plan-level approval.
- Subprocess guardrail (`_runtime/sandbox.py`) is the *only* execution mechanism. No `exec()`, no thread-based isolation. It is a guardrail against agent mistakes, not a security boundary.
- All MCP tool returns must use `biobabel.mcp.envelope.success(...)` / `error(...)`.
- biobabel core hosts no domain-specific AST detectors. Producer packages register detectors under the `biobabel.detectors` entry-point group; YAML `AntiPatternSpec.detection.detector_id` references those registrations.

## Adding a new MCP tool

1. Add the handler in `src/biobabel/mcp/tools/<group>.py`.
2. Register in `src/biobabel/mcp/server.py`.
3. Add an envelope-checking unit test in `tests/mcp/test_<group>.py`.
4. Update the tool count in `final_plan.md` §6 and the README if it changes.

## Adding a Pydantic model field

- Schema is at integer version v1. Additive-only: new optional fields OK, semantic changes are not. If you must break, bump to v2 (requires plan-level decision).
- After adding a field, regenerate the lock: `biobabel export-schema --version 1 > src/biobabel/data/schemas/manifest.v1.json`.

## Running tests

```bash
pip install -e '.[dev]'
pytest -xvs
```

To test MCP smoke end-to-end against the local `rgrid-python` checkout:

```bash
pip install -e '../Bio-Babel-public/rgrid-python'
biobabel index
biobabel validate package --pkg grid_py
```
