# AGENTS.md — guidance for AI agents working in this repo

This file is loaded by Claude Code / Cursor / Codex / Continue / etc. when working *inside* the `biobabel` repository itself.

(Note: `biobabel` is the read-only contract layer *for downstream Bio-Babel packages*. When an agent uses `biobabel` from a user's project, the relevant guidance is shipped via the Claude Code plugin's skills, not via this file.)

## Hard rules

1. **No reflection fallback.** `biobabel` only sees upstream packages that ship a `_biobabel/` contract directory. There is no inspection-based degraded mode. Tests assert this; do not weaken.
2. **No legacy / no backward-compat shims.** This is a fresh repo (not a continuation of `bio-babel-harness`). Do not add `_legacy/`, `aibio.*`, or `bio-babel-harness` aliases.
3. **Contract is mandatory.** Per the contract matrix in `docs/architecture.md`, missing required files → package unregistered. Do not add "partial" or "degraded" modes.
4. **MCP first.** All agent-facing functionality must be reachable through an MCP tool. CLI exists for human maintainers, not agents.

## Code conventions

- Python 3.10+, `from __future__ import annotations` everywhere.
- Pydantic v2 for all schemas. Models live in `src/biobabel/manifest_api.py` and are re-exported.
- Internal-only modules are prefixed `_` (`_registry/`, `_contracts/`, `_concept/`, `_retrofit/`, `_exporters/`). Two public Python surfaces: `biobabel.manifest_api` (contract schemas) and `biobabel.detector_api` (AST detector types — `DetectorMatch`, `DetectorFn`). Adding a third public surface requires plan-level approval.
- biobabel never executes agent-authored code. `check_code` is a *static* AST scan (`_concept/policy.py`): a default-deny import/call policy plus the producer's anti-pattern detectors. No `exec()`, no `subprocess`, no in-process eval — running snippets is the calling agent's job.
- All MCP tool returns must use `biobabel.mcp.envelope.success(...)` / `error(...)`.
- biobabel core hosts no domain-specific AST detectors. Producer packages register detectors under the `biobabel.detectors` entry-point group; YAML `AntiPatternSpec.detection.detector_id` references those registrations.

## Adding a new MCP tool

1. Add the handler in `src/biobabel/mcp/tools/<group>.py`.
2. Register in `src/biobabel/mcp/server.py`.
3. Add an envelope-checking unit test in `tests/test_mcp_server.py` (or `tests/test_<group>.py`).
4. If the tool count changes, update it in lockstep everywhere it is asserted or advertised: the `tool_count` assertion in `tests/test_mcp_server.py`, the `"N read-only MCP tools"` strings asserted in `tests/test_skills.py`, the overview generator `src/biobabel/_exporters/skills.py`, the shipped plugin overviews + manifests under `plugin/` and `.claude-plugin/marketplace.json`, and `docs/architecture.md`.

## Adding a Pydantic model field

- Schema is at integer version v1. Additive-only: new optional fields OK, semantic changes are not. If you must break, bump to v2 (requires plan-level decision).
- After adding a field, emit the JSON Schema to eyeball it with `biobabel export-schema` (stdout, or `--out <path>`). There is no committed schema lock file to regenerate.

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
