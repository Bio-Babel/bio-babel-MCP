# biobabel architecture

> What `biobabel` actually is and how the pieces fit. Read this once before
> contributing or before deciding whether you want to use it.

## TL;DR

`biobabel` is a **read-only contract layer**. It runs no business logic itself. It connects two sides:

| Side | Who writes here | What they write |
|------|-----------------|-----------------|
| **Producer side** — upstream package | Bio-Babel maintainers (you) | a `_biobabel/` directory with YAML contracts, plus a Python entry-point declaration |
| **Consumer side** — end user / IDE  | end users running `biobabel install --target X` | wiring that points their MCP-aware IDE (Claude Code, Cursor, Continue, Codex) at the local `biobabel-mcp` server |

biobabel sits in the middle. At runtime it discovers the producer-side contracts via Python entry points and exposes them to the consumer side as 12 read-only MCP tools for contract discovery and static snippet linting. biobabel does not execute code — running it is the calling agent's job.

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

Every upstream Bio-Babel package (rgrid-python, ggplot2-python, monocle2-python, monocle3-python, ...) ships a `_biobabel/` directory **inside its source tree**. biobabel **does not** introspect upstream code via reflection or signature scraping. No contract → biobabel can't see the package. This is hard policy, not a heuristic — it is enforced by the single discovery path in `_registry/discovery.py`, which has no reflection fallback.

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

Beyond these queryable lists, `package.yaml` carries package-level metadata — `import_name`, `distribution`, `display_name`, `contract_class`, `tier`, `maturity`, `foundation` (dependency facts, e.g. `ggplot2_py → grid_py`), `complements`, and an optional `r_package` reference — plus an optional `compositions` list (parent/child grammar constraints, loadable from a `compositions/` directory). Everything in `package.yaml` is returned verbatim by `describe_package`; `compositions` has no dedicated query tool of its own. Note the manifest no longer carries package-level routing hints (`triggers` / `task_tags` / `capabilities` / `not_when`): the agent ranks packages itself from the identity + classification fields above.

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

The load-bearing line is the `biobabel.manifest` entry point — that is the only thing biobabel reads at runtime. The `[tool.biobabel]` table is convenience metadata written by `biobabel new contract`; nothing in biobabel parses it at runtime, and the authoritative `contract_class` is the one inside the manifest (`package.yaml`).

Discovery walks exactly that one entry-point group (`_registry/discovery.py`) and calls each factory; the registry then indexes the results by import name and by every contract id (`_registry/builder.py`). Simplified:

```python
# _registry/discovery.py — load every manifest entry point
for ep in entry_points(group="biobabel.manifest"):
    manifest = ep.load()()                      # call get_manifest() -> PackageManifest

# _registry/builder.py — index by import name, then index every symbol/idiom/... by id
registry.packages[manifest.import_name] = manifest
```

Loading is strict, never best-effort: a factory that fails to load, raises, returns the wrong type, or collides on an already-registered id (package import name, symbol, workflow, template, concept, idiom, or anti-pattern id) is recorded as an explicit `DiscoveryError` — surfaced by `biobabel doctor` and in `list_packages`' output — rather than silently skipped.

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
biobabel install --target codex
biobabel install --target all          # claude_code + cursor + continue + codex
```

Each `--target` writes the IDE-specific config file so the IDE knows it has an MCP server called `biobabel` available:

| target          | file written                              | what it says |
|-----------------|-------------------------------------------|--------------|
| `claude_code`   | `~/.claude/settings.json`                 | stdio MCP server `biobabel`, launched via `biobabel-mcp` |
| `cursor`        | `~/.cursor/mcp.json` + `<workspace>/.cursor/rules/biobabel.md` | server config + a rule reminding the LLM to use biobabel when it sees R syntax |
| `continue`      | `~/.continue/config.yaml`                 | adds biobabel to Continue's `mcpServers` list (YAML schema) |
| `codex`         | `~/.codex/config.toml`                    | a `[mcp_servers.biobabel]` table, merged via `tomlkit` so existing settings + comments survive |
| `openai`        | `<workspace>/biobabel.tools.json` + `biobabel.system_prompt.md` | for OpenAI-Assistants-style MCP bridges |
| `all`           | claude_code + cursor + continue + codex   | `openai` is opt-in and **not** included in `all` |

Every install is additive and idempotent — re-running it overwrites the same `biobabel` key rather than duplicating it. The symmetric `biobabel uninstall --target X` removes only the `biobabel` entry (never keys it didn't write), with `--dry-run` to preview and `--force` to delete workspace artefacts that have been edited. Implementation: `src/biobabel/_exporters/installer.py`.

After `biobabel install --target claude_code`, when the user opens Claude Code, the IDE reads `~/.claude/settings.json`, sees the `biobabel` server, and is ready to launch `biobabel-mcp` as a subprocess on demand.

Claude Code and Codex additionally have a **full plugin** (`plugin/biobabel/` and `plugin/biobabel-codex/`, advertised by the marketplace manifests `.claude-plugin/marketplace.json` and `.agents/plugins/marketplace.json`) that bundles the MCP server *plus* an R-paste detector hook and the per-package `SKILL.md` files. `biobabel install` is the lighter MCP-only path for Cursor / Continue / OpenAI / any generic MCP client (or for a bare MCP wiring of Claude Code / Codex without the hook and skills).

## The MCP surface — 12 read-only tools

`biobabel-mcp` exposes exactly 12 tools. All are read-only, and all return the same `{ok, tool_name, summary, outputs, warnings, ...}` envelope (`mcp/envelope.py`). Clients enumerate them with the standard MCP `tools/list` method — there is no bespoke meta/`list_tools` tool. They fall into three groups (`mcp/tools/{discovery,concept,validation}.py`):

**Contract discovery (8)** — `list_*` / `describe_*` pairs over the manifest's queryable objects:

| Tool | Returns |
|------|---------|
| `biobabel.list_packages` | registered packages (filter by `contract_class` / `tier` / `maturity`) + any discovery errors |
| `biobabel.describe_package` | the full manifest for one import name |
| `biobabel.list_workflows` / `biobabel.describe_workflow` | reference workflows — it *lists* them, it does not choose a plan |
| `biobabel.list_symbols` / `biobabel.describe_symbol` | symbol contracts; `list_symbols` takes `query=` + `limit=` because a Tier-1 package can carry ~1k symbols and a bare list is a context bomb |
| `biobabel.list_templates` / `biobabel.describe_template` | reusable code/script skeletons |

**Concept layer (3):** `biobabel.describe_concept` (one invariant by id), `biobabel.list_idioms`, and `biobabel.describe_idiom` (idiom + a verbatim code template). There is no `list_concepts` — concepts surface through `describe_package` or by id.

**Validation (1):** `biobabel.check_code` — *static* lint only. It runs an AST import/call policy scan (`_concept/policy.py`, default-deny on network/shell/process modules and `eval`/`exec`/`open`/...) plus the target package's anti-pattern detectors (`_concept/anti_pattern_detector.py`). It returns the issues; it never executes the snippet.

The tool `inputSchema`s are derived automatically from each handler's keyword-only parameters (`mcp/schema.py`), so the advertised wire schema cannot drift from the code. The transport is line-delimited JSON-RPC 2.0 over stdio (`mcp/transports/stdio.py`, protocol version `2024-11-05`); because every tool returns a single envelope there is no streaming or progress-notification path.

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
        │  returns each package's identity + classification: import_name /
        │  distribution / version / contract_class / tier / maturity /
        │  display_name / foundation — the LLM ranks for itself
        │
        ▼
Returns: [{import_name: "grid_py", contract_class: "grammar", foundation: [...], ...}, ...]
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
│   ├── manifest_api.py         ← public contract schemas (Pydantic v2 models, schema v1)
│   ├── detector_api.py         ← public detector callable types (DetectorFn / DetectorMatch)
│   ├── _registry/
│   │   ├── discovery.py        ← entry-point discovery of manifests + detectors (no reflection fallback)
│   │   ├── builder.py          ← Registry: in-memory id indexes + duplicate detection
│   │   └── sha.py              ← stable manifest hash (provenance stamp for generated skills)
│   ├── _contracts/validator.py ← _biobabel/ directory validator (`biobabel validate package`)
│   ├── _concept/               ← idiom search + anti-pattern AST detector + check_code import/call policy
│   ├── _retrofit/              ← `biobabel new contract` — introspect an existing pkg, emit _biobabel/ skeleton
│   ├── _exporters/             ← install/uninstall (installer.py) + `build-skills` SKILL.md generation (skills.py)
│   ├── mcp/                    ← 12 read-only tools (tools/{discovery,concept,validation}.py),
│   │                             auto-derived input schemas (schema.py), JSON-RPC stdio transport
│   └── cli/                    ← biobabel CLI (click)
└── tests/                      ← unit tests covering all of the above
```

The CLI (`cli/__main__.py`, for human maintainers — agents go through MCP) exposes: `index` and `doctor` (discovery health), `validate package`, `new contract`, `build-skills`, `install` / `uninstall`, `export-schema`, and `mcp` (launch the stdio server).

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

1. `importlib.util.find_spec(import_name)` to locate the source tree *without executing it* (so it works even when the package's top-level import needs an unavailable C-extension).
2. Refuses if `_biobabel/` already exists (requires `--force`).
3. Introspects the public surface two ways: import the package and read `inspect.signature` over `__all__` (or `dir()`-filtered) when the import succeeds; otherwise AST-parse `__init__.py` to recover the `from .submod import ...` map and emit signature-less stubs for the submodules that can't be imported.
4. Heuristically guesses `contract_class` (enough `adata`/`cds`-first-arg mutators → analysis; enough `plot_*`/`vis_*`/`draw_*` helpers → grammar; analysis as the safe default).
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

**This is dev-time scaffolding, not runtime reflection.** The introspection output is frozen into YAML on disk for you to review and edit. At MCP-server-time biobabel only reads the YAML, never re-introspects. The `_biobabel/`-is-mandatory, no-reflection-at-runtime invariant is preserved.

After running:

```bash
# Edit the TODO-tagged fields in the generated YAML, then:
biobabel validate package --pkg <import_name> --strict
```

Once that returns OK, your package is biobabel-discoverable. Add the validate command as a CI step so the contract can't drift silently.
