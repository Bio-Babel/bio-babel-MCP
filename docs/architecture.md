# biobabel architecture

> What `biobabel` actually is and how the pieces fit. Read this once before
> contributing or before deciding whether you want to use it.

## TL;DR

`biobabel` is a **control plane**. It runs no business logic itself. It connects two sides:

| Side | Who writes here | What they write |
|------|-----------------|-----------------|
| **Producer side** — upstream package | Bio-Babel maintainers (you) | a `_biobabel/` directory with YAML contracts, plus a Python entry-point declaration |
| **Consumer side** — end user / IDE  | end users running `biobabel install --target X` | wiring that points their MCP-aware IDE (Claude Code, Cursor, Continue, Codex) at the local `biobabel-mcp` server |

biobabel sits in the middle. At runtime it discovers the producer-side contracts via Python entry points and exposes them to the consumer side as 15 read-only MCP tools for contract discovery, snippet linting, and health metadata. biobabel does not execute code — running it is the calling agent's job.

```
┌──────────────────────────────────┐         ┌──────────────────────────────────┐
│  Producer side                    │         │  Consumer side                    │
│  (Bio-Babel maintainers)          │         │  (end users + their agents)       │
│                                   │         │                                   │
│  1. Add _biobabel/ to upstream   │         │  3. pip install biobabel          │
│  2. Declare entry_point          │ ──MCP──>│  4. biobabel install --target X   │
│                                   │         │  5. agent calls biobabel.* tools  │
└──────────────────────────────────┘         └──────────────────────────────────┘
```

## The two halves in detail

### Producer side — the `_biobabel/` contract

> "Here is everything an agent needs to know to use my package correctly."

Every upstream Bio-Babel package (rgrid-python, ggplot2-python, monocle2-python, monocle3-python, ...) ships a `_biobabel/` directory **inside its source tree**. biobabel **does not** introspect upstream code via reflection or signature scraping. No contract → biobabel can't see the package. This is hard policy, not a heuristic (see §0.4 of `final_plan.md`).

The minimum mandatory shape:

```
your_pkg/_biobabel/
├── __init__.py            # factory: get_manifest() -> PackageManifest
└── package.yaml           # schema_version, contract_class, metadata, optional inline contracts
```

Recommended supporting files:

```
your_pkg/_biobabel/
├── skill.md               # narrative explanation for the LLM
└── examples/smoke.py      # CI smoke check for producer maintainers
```

Queryable contract objects may be declared inline in `package.yaml` or split
into YAML files under these directories:

| File / dir       | Class A (Analysis) | Class B (Grammar) | Class AB (Mixed) |
|------------------|:------------------:|:-----------------:|:----------------:|
| `symbols/`       | required           | recommended       | required         |
| `workflows/`     | recommended        | optional          | optional         |
| `templates/`     | optional           | optional          | optional         |
| `concepts/`      | optional           | recommended       | recommended      |
| `idioms/`        | optional           | recommended       | recommended      |
| `anti_patterns/` | optional           | recommended       | recommended      |

`symbols/` is the exact call surface: signatures, parameters, state reads/writes, examples, and failure fixes. `workflows/` is only a linear reference description for the agent to plan from: each step has `symbol`, `purpose`, optional `args`, and optional `notes`. There is no `next` field, no prerequisite checker, and no workflow executor in biobabel.

### Producer side — the entry point

biobabel discovers upstream packages through the standard Python entry-point mechanism (PEP 621 / `importlib.metadata`). Two lines in the upstream package's `pyproject.toml`:

```toml
[tool.biobabel]
contract_class = "grammar"           # | "analysis" | "mixed"

[project.entry-points."biobabel.manifest"]
grid_py = "grid_py._biobabel:get_manifest"
```

What this means:

> When anyone (in this case, biobabel) iterates entry points in the
> `biobabel.manifest` group, they will find a hook named `grid_py` that
> resolves to the callable `grid_py._biobabel.get_manifest`. Calling it
> returns a `PackageManifest`.

biobabel's discovery code (`src/biobabel/_registry/discovery.py`) is literally:

```python
for ep in entry_points(group="biobabel.manifest"):
    manifest = ep.load()()       # call get_manifest()
    registry.add(ep.name, manifest)
```

Consequence: **whatever Bio-Babel packages the user has `pip install`-ed are exactly what biobabel sees**. Install rgrid + ggplot2 + monocle2py → biobabel returns three packages. Uninstall one → it disappears. Zero configuration on the user side.

### Producer side — registering AST anti-pattern detectors

A second entry-point group, `biobabel.detectors`, lets producers ship the
Python callables behind their `AntiPatternSpec.detection.detector_id` YAML
fields. Example from `rgrid-python`:

```toml
[project.entry-points."biobabel.detectors"]
"rgrid.for_loop_calls" = "grid_py._biobabel.detectors:for_loop_calls"
"rgrid.unbalanced"     = "grid_py._biobabel.detectors:unbalanced"
"rgrid.unit_kw"        = "grid_py._biobabel.detectors:unit_kw"
```

Each callable satisfies the `biobabel.detector_api.DetectorFn` signature:
`(ast.AST, dict[str, Any]) -> list[DetectorMatch]`. Each YAML anti-pattern
selects one via:

```yaml
detection:
  detector_id: rgrid.for_loop_calls
  args:
    calls: [rect_grob, text_grob, ...]
```

biobabel core ships **zero built-in detectors**. The grammar/anti-pattern
knowledge lives in the package that owns the domain — that's the whole
point of the producer-side contract.

### Consumer side — installing biobabel

A user (or their agent acting through `pip`) runs:

```bash
pip install biobabel
```

This installs the Python package and two console scripts: `biobabel` (CLI) and `biobabel-mcp` (the MCP stdio server). At this point biobabel is *importable* but **not yet wired into any IDE** — the IDEs run as separate processes and need to be told about it.

### Consumer side — wiring biobabel into an IDE

```bash
biobabel install --target claude_code
biobabel install --target cursor
biobabel install --target continue
biobabel install --target all
```

Each `--target` writes the IDE-specific config file so the IDE knows it has an MCP server called `biobabel` available:

| target          | file written                              | what it says |
|-----------------|-------------------------------------------|--------------|
| `claude_code`   | `~/.claude/settings.json`                 | "There's a stdio MCP server, launch it with `biobabel-mcp`" |
| `cursor`        | `~/.cursor/mcp.json` + `<workspace>/.cursor/rules/biobabel.md` | server config + a rule reminding the LLM to use biobabel when it sees R syntax |
| `continue`      | `~/.continue/config.yaml`                 | adds biobabel to Continue's MCP server list |
| `openai`        | `<workspace>/biobabel.tools.json` + system prompt | for OpenAI-Assistants-style bridges |
| `all`           | does claude_code + cursor + continue      |              |

Implementation: `src/biobabel/_exporters/installer.py`.

After `biobabel install --target claude_code`, when the user opens Claude Code, the IDE reads `~/.claude/settings.json`, sees the `biobabel` server, and is ready to launch `biobabel-mcp` as a subprocess on demand.

## End-to-end flow (the moment of value)

Concrete sequence, from a user request to a delivered artifact:

```
User in Claude Code: "Use rgrid to draw a 2x2 multi-panel figure."
        │
        ▼
Claude Code (read ~/.claude/settings.json at startup → knows about biobabel)
        │  spawn subprocess: biobabel-mcp  (stdio JSON-RPC)
        ▼
biobabel-mcp boots → build_registry()
        │
        │  entry_points(group="biobabel.manifest")
        │  → finds the `grid_py` entry point installed by rgrid-python
        │  → loads grid_py/_biobabel/__init__.py:get_manifest()
        │  → reads ALL the YAML files in _biobabel/ into a PackageManifest
        │
        ▼
LLM (planning):  biobabel.list_packages()
        │
        │  returns every registered package with triggers / task_tags /
        │  capabilities / not_when / foundation — the LLM ranks itself
        │
        ▼
Returns: [{import_name: "grid_py", triggers: [...], task_tags: [...], ...}, ...]
        │
        ▼
LLM:  biobabel.describe_idiom(idiom_id="grid_py.nested_viewport")
        │
        │  registry lookup → grid_py/_biobabel/idioms/nested_viewport.yaml
        │
        ▼
Returns: IdiomSpec including a verbatim code template
        │
        ▼
LLM writes code based on the template
        │
        ▼
LLM:  biobabel.check_code(code, package="grid_py")
        │
        │  AST scan + run grid_py's anti_patterns/*.yaml detectors
        │
        ▼
Returns: {issues: []}   (no anti-pattern hit)
        │
        ▼
LLM:  runs the code with its OWN execution tool (terminal / python);
      user code imports grid_py, draws, writes multi_panel.png
        │
        ▼
LLM shows the artifact path or content to the user.
```

Note that biobabel itself **does not draw anything**, **does not understand grid graphics**, and **does not run code**. All it does:

1. Discovers what packages exist (entry points)
2. Reads their declared concepts / idioms / anti-patterns (YAML)
3. Surfaces them as read-only MCP tools (envelope + dispatch)
4. Statically lints agent-drafted snippets on request (`check_code`: AST policy scan + the package's anti-pattern detectors)

The actual *knowledge* lives in each upstream package's `_biobabel/`. Execution is the calling agent's job, with the agent's own tools.

### Multi-step analyses keep state on disk

biobabel holds no session object and no hidden AnnData handle — it never executes code. When an analysis is naturally multi-step, the agent runs each step with its own execution tool and persists intermediate state into a file, reading it back for the next step.

For AnnData workflows, the recommended state carrier is an `.h5ad` file:

```python
# step 1: initialise and persist intermediate state
import anndata as ad
import monocle2py as m2

adata = ad.read_h5ad("hematopoiesis_raw.h5ad")
m2.new_cell_dataset(adata)
m2.detect_genes(adata)
m2.estimate_size_factors(adata)
adata.write_h5ad("step1_size_factors.h5ad")
```

```python
# step 2: resume from the previous artifact
import anndata as ad
import monocle2py as m2

adata = ad.read_h5ad("step1_size_factors.h5ad")
m2.estimate_dispersions(adata)
m2.set_ordering_filter(adata, ordering_genes=adata.var_names[:1000])
m2.reduce_dimension(adata, reduction_method="DDRTree")
m2.order_cells(adata, root_state=1)
adata.write_h5ad("step2_pseudotime.h5ad")
```

Using the filesystem as the state boundary makes each step reproducible from a visible artifact, and the per-step contracts (`describe_symbol`'s `requires` / `writes`) tell the agent exactly what each call needs and produces.

## Architectural invariants (do not break these)

1. **Contract is mandatory.** No `_biobabel/` → not registered. No reflection fallback. (See `_registry/discovery.py`: there is exactly one discovery code path.)
2. **Entry-point only.** biobabel never scans `site-packages/` looking for packages. The producer must declare itself.
3. **biobabel never executes code.** No subprocess, no `exec()`, no in-process eval. The agent runs code with its own tools; biobabel only reads contracts and statically lints snippets on request. The import/call policy used by `check_code` lives in `_concept/policy.py`.
4. **MCP-first.** Every agent-facing capability is reachable through a tool name like `biobabel.X`. The CLI exists for human maintainers.
5. **No silent degradation.** Missing manifests, broken entry points, duplicate ids, and unregistered detector ids surface as explicit discovery errors or tool errors. There is no "best effort" reflection mode.
6. **One internal schema version at a time.** Current manifest schema is v1. Until public release, breaking changes update v1 directly; no backward-compatibility layer is kept.

## Where the code lives

```
biobabel/
├── src/biobabel/
│   ├── manifest_api.py         ← public contract schemas (Pydantic models)
│   ├── detector_api.py         ← public detector callable types
│   ├── _registry/              ← entry-point discovery + in-memory indexes
│   ├── _contracts/             ← _biobabel/ directory validator
│   ├── _registry/search.py     ← deterministic lexical contract search
│   ├── _concept/               ← idiom search + anti-pattern AST detector + check_code static policy
│   ├── _retrofit/              ← `biobabel new contract` — introspect an existing pkg, emit _biobabel/ skeleton
│   ├── _exporters/             ← biobabel install --target X
│   ├── mcp/                    ← 15 read-only tools, JSON-RPC stdio transport
│   └── cli/                    ← biobabel CLI (click)
└── tests/                      ← unit tests covering all of the above
```

The leading underscore is intentional: everything except `manifest_api` and `detector_api` is private and may change. Upstream packages should import **only** `from biobabel.manifest_api import ...` and, when registering AST anti-pattern detectors, `from biobabel.detector_api import ...`.

## Naming convention: entry-point key is the import name, not the distribution name

```toml
[project.entry-points."biobabel.manifest"]
grid_py = "grid_py._biobabel:get_manifest"     # ← import name (what `import X` uses)
#  ↑                                              not the PyPI distribution name (rgrid-python)
```

Python has two parallel namespaces: **distribution** (`pip install rgrid-python`) and **import** (`import grid_py`). PyPI uniqueness rules sometimes force them apart (`rgrid-python` exists because `grid` and `grid-py` were blocked).

biobabel keys its registry by **import name** because:
1. Agents only ever write `import grid_py` / `grid_py.Viewport` — they never type the distribution name in code.
2. MCP tool arguments (`describe_package(import_name=...)`, `list_idioms(package=...)`, `check_code(package=...)`) all use the import name.
3. Two installed packages cannot share an import name, so there's no collision risk.

The PyPI distribution name is preserved separately in `package.yaml::distribution` so `biobabel install`-style hints and `pip` messages can still surface it.

## Adding a new upstream package — `biobabel new contract`

For an existing installable Python package, biobabel ships a one-shot retrofit command:

```bash
pip install -e .                                  # ensure your package is importable
biobabel new contract --pkg <import_name>         # introspect + emit _biobabel/ skeleton
                       [--class analysis|grammar|mixed]
                       [--r-package <r_name>]
                       [--dry-run] [--force]
```

What it does (one shot, NOT runtime reflection):

1. `importlib.import_module(import_name)` to locate the source tree.
2. Refuses if `_biobabel/` already exists (requires `--force`).
3. `inspect.signature` over `__all__` (or `dir()`-filtered) to enumerate public callables/classes.
4. Heuristically guesses `contract_class` (`adata` first param → analysis; `plot_*` names → grammar).
5. Writes `_biobabel/` with:
   - `__init__.py` (working `get_manifest()` factory)
   - `package.yaml` (TODO-marked fields you must edit)
   - `skill.md`, `examples/smoke.py`, `templates/README_TODO.md`
   - `symbols/<name>.yaml` for each detected public callable/class
   - `workflows/README_TODO.md` placeholders (Class A/AB)
   - `concepts/idioms/anti_patterns/README_TODO.md` placeholders (Class B/AB)
6. Additively patches `pyproject.toml` via `tomlkit` (preserves your existing comments + ordering):
   ```toml
   [tool.biobabel]
   contract_class = "analysis"

   [project.entry-points."biobabel.manifest"]
   <import_name> = "<import_name>._biobabel:get_manifest"
   ```
7. Prints a TODO checklist sorted by priority (top-5 symbols by parameter count first).

**This is dev-time scaffolding, not runtime reflection.** The introspection output is frozen into YAML on disk for you to review and edit. At MCP-server-time biobabel only reads the YAML, never re-introspects. The `_biobabel/` hard constraint (§0.4) is preserved.

After running:

```bash
# Edit the TODO-tagged fields in the generated YAML, then:
biobabel validate package --pkg <import_name> --strict
```

Once that returns OK, your package is biobabel-discoverable. Add the validate command as a CI step so the contract can't drift silently.
