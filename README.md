# biobabel

[![CI](https://github.com/Bio-Babel/bio-babel/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Bio-Babel/bio-babel/actions/workflows/ci.yml)

> Agent consumption layer for the [Bio-Babel](https://github.com/Bio-Babel) repositories.

## Two scenarios it serves

| Scenario | Example ask | What biobabel gives the agent |
|----------|-------------|-------------------------------|
| Run an analysis using a registered package | *"use monocle3 to compute pseudotime on this AnnData"* | state-machine pipeline contract (6 steps with `requires` / `writes` / `next`), per-step prerequisite check, sandboxed execution |
| Build new Python code on a foundation package | *"draw an N×N panel grid using grid_py"* | concept layer (Viewport / Grob / Unit / Gpar invariants), idiom library, AST-based anti-pattern detection |

## Install

```bash
pip install biobabel monocle3-python ggplot2-python
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
