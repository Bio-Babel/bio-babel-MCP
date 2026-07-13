<img align="right" width="240" alt="biobabel logo" src="assets/biobabel-logo.svg">

# biobabel

[![CI](https://github.com/Bio-Babel/bio-babel/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Bio-Babel/bio-babel/actions/workflows/ci.yml)

> Agent consumption layer for the [Bio-Babel](https://github.com/Bio-Babel) repositories.

## Two scenarios it serves

| Scenario | Example ask | What biobabel gives the agent |
|----------|-------------|-------------------------------|
| Run an analysis using a registered package | *"use monocle2py to compute pseudotime on this AnnData"* | exact symbol contracts, linear reference workflows, reusable templates, and static code checking |
| Build new Python code on a foundation package | *"draw an N×N panel grid using grid_py"* | exact symbol contracts, concept invariants, idiom library, reusable templates, and AST-based anti-pattern detection |

biobabel does **not** plan the analysis for the agent and does **not** execute code — it just provides accurate API guidance for the agent's coding.

## Install

```bash
pip install biobabel monocle2-python ggplot2-python
biobabel index    # confirms discovery, lists registered packages
```

## Plug into your agent IDE

For **Claude Code** — full plugin (MCP + hook + skills):

```
/plugin marketplace add Bio-Babel/bio-babel
/plugin install biobabel@bio-babel
```

Or install from a local clone:

```bash
git clone https://github.com/Bio-Babel/bio-babel.git
```

```
/plugin marketplace add ./bio-babel      # or an absolute path to the clone
/plugin install biobabel@bio-babel
```

Since the clone is a git repo, `/plugin marketplace update` pulls later changes.

For **Codex** — full plugin (MCP + hook + skills), via Codex's own plugin format
(`plugin/biobabel-codex/`, marketplace manifest at `.agents/plugins/marketplace.json`):

```
codex plugin marketplace add Bio-Babel/bio-babel
# then enable "biobabel" from the /plugins menu
```

For **Cursor / Continue / OpenAI / generic MCP** (or just the bare MCP server for
Claude Code / Codex) — no plugin, MCP wiring only:

```bash
biobabel install   --target cursor     # or continue | codex | openai | claude_code | all
biobabel uninstall --target cursor     # symmetric inverse; --dry-run to preview, --force to remove user-modified workspace files
```

`--target codex` registers `biobabel-mcp` in `~/.codex/config.toml` under
`[mcp_servers.biobabel]`, while preserving your other Codex settings.

## Register your own package into the ecosystem

If you've written a Python port of an R bioinformatics package and want agents to discover it:

```bash
pip install -e .                              # your package must be importable
biobabel new contract --pkg <import_name>     # emit _biobabel/ skeleton + patch pyproject.toml
$EDITOR <pkg>/_biobabel/...                   # fill the YAML stubs
biobabel validate package --pkg <import_name> --strict
```

#### Optional — register AST anti-pattern detectors

If your `_biobabel/anti_patterns/*.yaml` uses AST-level detection (anything beyond plain `regex:`), ship the detector callables alongside the manifest. biobabel core has **no built-in detectors** — every AST rule lives in the package that owns the domain.

1. Write `<pkg>/_biobabel/detectors.py`, with functions matching `biobabel.detector_api.DetectorFn`:
   ```python
   from biobabel.detector_api import DetectorMatch

   def for_loop_calls(tree, args) -> list[DetectorMatch]:
       ...  # return DetectorMatch(line=..., detail={...}) per hit
   ```
2. Register them in `pyproject.toml`:
   ```toml
   [project.entry-points."biobabel.detectors"]
   "mypkg.for_loop_calls" = "mypkg._biobabel.detectors:for_loop_calls"
   ```
3. Reference each by `detector_id` in the relevant YAML:
   ```yaml
   detection:
     detector_id: mypkg.for_loop_calls
     args:
       calls: [foo, bar]
   ```

Pure-regex anti-patterns (no AST walk needed) skip this — `detection.regex:` alone is enough. The canonical Class B example with three AST detectors is [`rgrid-python`](https://github.com/Bio-Babel/rgrid-python).

After publishing, agents in any biobabel-wired IDE discover your package automatically (via Python entry points — no central registry).

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — full design (read this first)
- [`AGENTS.md`](AGENTS.md) — conventions for AI agents working inside this repo

## License

MIT.
