"""Write IDE configuration files for each supported MCP client.

## Wire formats this writes

### Claude Code (`~/.claude/settings.json`)

```jsonc
{
  "mcpServers": {
    "biobabel": {
      "command": "biobabel-mcp",
      "args": []
    }
  }
}
```

(See https://docs.claude.com/en/docs/claude-code/mcp.)

### Cursor (`~/.cursor/mcp.json`)

```jsonc
{
  "mcpServers": {
    "biobabel": {
      "command": "biobabel-mcp",
      "args": []
    }
  }
}
```

Plus a per-workspace rule at `<workspace>/.cursor/rules/biobabel.md` (Cursor
auto-loads `.cursor/rules/*.md`).

### Continue (`~/.continue/config.yaml`)

Continue moved to YAML in late 2025; the legacy `config.json` is still
honored but `config.yaml` takes precedence when both exist. We write
`config.yaml`. The `mcpServers` block is keyed by name.

```yaml
mcpServers:
  - name: biobabel
    command: biobabel-mcp
    args: []
```

## Idempotence

All installers are *additive and idempotent*: re-running `biobabel install`
will not duplicate the entry; it overwrites the same `biobabel` key with the
current value.

## Environment overrides

For tests, the following env vars redirect the install paths:

| target      | env var          | default              |
|-------------|------------------|----------------------|
| claude_code | `CLAUDE_HOME`    | `~/.claude`          |
| cursor      | `CURSOR_HOME`    | `~/.cursor`          |
| continue    | `CONTINUE_HOME`  | `~/.continue`        |
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

MCP_SERVER_KEY = "biobabel"
MCP_SERVER_COMMAND = "biobabel-mcp"


def install(target: str, workspace: Path) -> list[Path]:
    workspace = workspace.resolve()
    if target == "all":
        out: list[Path] = []
        out.extend(install("claude_code", workspace))
        out.extend(install("cursor", workspace))
        out.extend(install("continue", workspace))
        return out
    if target == "claude_code":
        return _install_claude_code()
    if target == "cursor":
        return _install_cursor(workspace)
    if target == "continue":
        return _install_continue()
    if target == "openai":
        return _install_openai(workspace)
    raise ValueError(f"unknown target: {target}")


def _install_claude_code() -> list[Path]:
    home = Path(os.environ.get("CLAUDE_HOME", str(Path.home() / ".claude")))
    settings_path = home / "settings.json"
    settings = _read_json(settings_path)
    settings.setdefault("mcpServers", {})[MCP_SERVER_KEY] = {
        "command": MCP_SERVER_COMMAND,
        "args": [],
    }
    _write_json(settings_path, settings)
    return [settings_path]


def _install_cursor(workspace: Path) -> list[Path]:
    home = Path(os.environ.get("CURSOR_HOME", str(Path.home() / ".cursor")))
    mcp_path = home / "mcp.json"
    config = _read_json(mcp_path)
    config.setdefault("mcpServers", {})[MCP_SERVER_KEY] = {
        "command": MCP_SERVER_COMMAND,
        "args": [],
    }
    _write_json(mcp_path, config)

    rules_dir = workspace / ".cursor" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    rule_path = rules_dir / "biobabel.md"
    rule_path.write_text(_BIOBABEL_RULE, encoding="utf-8")
    return [mcp_path, rule_path]


def _install_continue() -> list[Path]:
    """Write Continue's `config.yaml` `mcpServers` block (YAML format, current schema)."""
    home = Path(os.environ.get("CONTINUE_HOME", str(Path.home() / ".continue")))
    config_path = home / "config.yaml"
    config = _read_yaml(config_path)
    servers = config.setdefault("mcpServers", [])
    if not isinstance(servers, list):
        raise RuntimeError(
            f"{config_path}: 'mcpServers' must be a list (YAML schema), found {type(servers).__name__}"
        )
    # Idempotence: replace existing entry with our name; otherwise append.
    new_entry = {
        "name": MCP_SERVER_KEY,
        "command": MCP_SERVER_COMMAND,
        "args": [],
    }
    for i, server in enumerate(servers):
        if isinstance(server, dict) and server.get("name") == MCP_SERVER_KEY:
            servers[i] = new_entry
            break
    else:
        servers.append(new_entry)
    _write_yaml(config_path, config)
    return [config_path]


def _install_openai(workspace: Path) -> list[Path]:
    tools_path = workspace / "biobabel.tools.json"
    tools_path.write_text(
        json.dumps(
            {
                "tools_endpoint": "biobabel-mcp via stdio",
                "transport": "stdio",
                "note": "Bridge through any MCP→OpenAI tool adapter.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    prompt_path = workspace / "biobabel.system_prompt.md"
    prompt_path.write_text(_BIOBABEL_RULE, encoding="utf-8")
    return [tools_path, prompt_path]


# --- I/O helpers ----------------------------------------------------------


def _read_json(path: Path) -> dict:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _read_yaml(path: Path) -> dict:
    if path.is_file():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    return {}


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


# --- Rule text used by Cursor + openai prompt ----------------------------


_BIOBABEL_RULE = """# biobabel

biobabel is the agent control plane for the Bio-Babel ecosystem (R-to-Python
bioinformatics ports). When the user mentions ggplot2, monocle3, pheatmap,
ComplexHeatmap, copykat, grid_py, gtable, scales, etc., reach for the
biobabel.* MCP tools first instead of guessing the Python API from R memory.

Key tools:
- biobabel.list_packages()         — every registered package with triggers/tags/capabilities/not_when; rank yourself
- biobabel.plan_workflow(task)     — Class A pipeline (Monocle3, copykat, ...)
- biobabel.check_prerequisites     — verify adata state before each step
- biobabel.describe_concept(id)    — Class B mental model (grid_py.Viewport, ...)
- biobabel.list_idioms(package)    — idiomatic patterns
- biobabel.describe_symbol(id)     — function signature + state-graph contract
- biobabel.check_code(code)        — anti-pattern detector
- biobabel.run_code / run_recipe   — sandboxed execution

Hard rule: if the user pastes R-style syntax (`library(`, `<-`, `%>%`,
`aes(displ, hwy)` without quotes), DO NOT translate line-by-line. Instead
call biobabel.describe_concept / describe_symbol / list_idioms to fetch the
Python API directly — the Python port may NOT mirror R 1:1.
"""
