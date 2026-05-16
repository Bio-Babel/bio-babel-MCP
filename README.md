# biobabel

> Agent consumption layer for the [Bio-Babel](https://github.com/Bio-Babel) repositories.

`pip install biobabel`, register the MCP server with your agent IDE, and your agent can accurately use any installed Bio-Babel package via **23 MCP tools** — without guessing R-style Python.

## Two scenarios it serves

| Scenario | Example ask | What biobabel gives the agent |
|----------|-------------|-------------------------------|
| Run an analysis using a registered package | *"use monocle3 to compute pseudotime on this AnnData"* | state-machine pipeline contract (6 steps with `requires` / `writes` / `next`), per-step prerequisite check, sandboxed execution |
| Build new Python code on a foundation package | *"draw an N×N panel grid using grid_py"* | concept layer (Viewport / Grob / Unit / Gpar invariants), idiom library, AST-based anti-pattern detection |

## Install

```bash
pip install biobabel rgrid-python monocle3-python ggplot2-python
biobabel index    # confirms discovery, lists registered packages
```

## Plug into your agent IDE

For **Claude Code** — full plugin (MCP + slash commands + hook + skills):

```
/plugin marketplace add Bio-Babel/bio-babel
/plugin install biobabel@bio-babel
```

For **Cursor / Continue / OpenAI / generic MCP** — bare MCP server:

```bash
biobabel install --target cursor       # or continue | openai | claude_code | all
```

## Register your own package into the ecosystem

If you've written a Python port of an R bioinformatics package and want agents to discover it:

```bash
pip install -e .                              # your package must be importable
biobabel new contract --pkg <import_name>     # emit _biobabel/ skeleton + patch pyproject.toml
$EDITOR <pkg>/_biobabel/...                   # fill the YAML stubs
biobabel validate package --pkg <import_name> --strict
```

After publishing, agents in any biobabel-wired IDE discover your package automatically (via Python entry points — no central registry).

## What's in the box

- **23 MCP tools** across 6 groups — `list_packages` · `recommend` · `plan_workflow` · `check_prerequisites` · `describe_concept` · `list_idioms` · `check_code` · `run_code` · `run_recipe` · ...
- **Claude Code plugin** — 2 slash commands (`/biobabel:recommend`, `/biobabel:plan`), 1 R-paste-detector hook, 6 generated skill files
- **CLI for maintainers and publishers** — `index`, `doctor`, `validate package`, `new contract`, `diff-api`, `build-skills`, `install`, `export-schema`

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — full design (read this first)
- [`AGENTS.md`](AGENTS.md) — conventions for AI agents working inside this repo

## License

MIT.
