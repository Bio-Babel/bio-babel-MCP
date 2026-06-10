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

### Codex CLI (`~/.codex/config.toml`)

Codex registers MCP servers under TOML `[mcp_servers.<name>]` tables — note the
snake_case key, unlike the JSON `mcpServers` used by Claude Code / Cursor. We
merge with `tomlkit`, so the user's other Codex settings *and comments* survive.

```toml
[mcp_servers.biobabel]
command = "biobabel-mcp"
args = []
```

Codex's only per-project guidance surface is the shared, user-curated
`AGENTS.md`; we do not touch it (no dedicated rules dir like Cursor's). Codex is
therefore MCP-config-only, like Claude Code and Continue.

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
| codex       | `CODEX_HOME`     | `~/.codex`           |
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import tomlkit
import yaml

MCP_SERVER_KEY = "biobabel"
MCP_SERVER_COMMAND = "biobabel-mcp"

# Canonical content of the workspace artefacts. Both install (which writes
# them) and uninstall (which decides whether they have been user-modified
# and therefore must be preserved) reference these same constants so the
# two stay coupled.
_OPENAI_TOOLS_PAYLOAD: dict[str, str] = {
    "tools_endpoint": "biobabel-mcp via stdio",
    "transport": "stdio",
    "note": "Bridge through any MCP→OpenAI tool adapter.",
}


def _openai_tools_text() -> str:
    return json.dumps(_OPENAI_TOOLS_PAYLOAD, indent=2)


def install(target: str, workspace: Path) -> list[Path]:
    workspace = workspace.resolve()
    if target == "all":
        out: list[Path] = []
        out.extend(install("claude_code", workspace))
        out.extend(install("cursor", workspace))
        out.extend(install("continue", workspace))
        out.extend(install("codex", workspace))
        return out
    if target == "claude_code":
        return _install_claude_code()
    if target == "cursor":
        return _install_cursor(workspace)
    if target == "continue":
        return _install_continue()
    if target == "codex":
        return _install_codex()
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


def _install_codex() -> list[Path]:
    """Merge ``[mcp_servers.biobabel]`` into Codex's ``config.toml`` (TOML schema)."""
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    config_path = home / "config.toml"
    doc = _read_toml(config_path)
    servers = doc.get("mcp_servers")
    if servers is None:
        doc["mcp_servers"] = tomlkit.table(is_super_table=True)
        servers = doc["mcp_servers"]
    elif not isinstance(servers, Mapping):
        raise RuntimeError(
            f"{config_path}: 'mcp_servers' must be a table (TOML schema), "
            f"found {type(servers).__name__}"
        )
    # Idempotence: overwrite the same key with the current value.
    entry = tomlkit.table()
    entry["command"] = MCP_SERVER_COMMAND
    entry["args"] = []
    servers[MCP_SERVER_KEY] = entry
    _write_toml(config_path, doc)
    return [config_path]


def _install_openai(workspace: Path) -> list[Path]:
    tools_path = workspace / "biobabel.tools.json"
    tools_path.write_text(_openai_tools_text(), encoding="utf-8")
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


def _read_toml(path: Path) -> tomlkit.TOMLDocument:
    if path.is_file():
        return tomlkit.parse(path.read_text(encoding="utf-8"))
    return tomlkit.document()


def _write_toml(path: Path, doc: tomlkit.TOMLDocument) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


# --- Rule text used by Cursor + openai prompt ----------------------------


# --- Uninstall ------------------------------------------------------------
#
# Symmetric inverse of ``install``. Two safety properties beyond what install
# guarantees:
#
# 1. ``--dry-run`` shows what would be removed without touching files.
# 2. Workspace artefacts (cursor's rule file, openai's tools+prompt files)
#    are preserved when their content has diverged from what install would
#    write today. ``--force`` overrides this and removes them anyway.
#
# We never reach into a config file to remove keys we didn't put there:
# only the ``mcpServers.biobabel`` entry is touched. If removing it leaves
# ``mcpServers`` empty, the empty container is kept — minimum-mutation
# principle. The user's other settings, tools, and YAML keys stay untouched.


@dataclass
class UninstallReport:
    """What ``uninstall`` did or would have done.

    ``actions`` is a human-readable log used by the CLI. The three structured
    lists let callers and tests reason about each outcome class precisely.
    """

    actions: list[str] = field(default_factory=list)
    removed: list[Path] = field(default_factory=list)
    kept_modified: list[Path] = field(default_factory=list)
    not_found: list[Path] = field(default_factory=list)

    def extend(self, other: UninstallReport) -> None:
        self.actions.extend(other.actions)
        self.removed.extend(other.removed)
        self.kept_modified.extend(other.kept_modified)
        self.not_found.extend(other.not_found)


def uninstall(
    target: str,
    workspace: Path,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> UninstallReport:
    workspace = workspace.resolve()
    if target == "all":
        report = UninstallReport()
        # Mirrors install("all", ...) — IDE targets only; openai is opt-in.
        report.extend(uninstall("claude_code", workspace, dry_run=dry_run, force=force))
        report.extend(uninstall("cursor", workspace, dry_run=dry_run, force=force))
        report.extend(uninstall("continue", workspace, dry_run=dry_run, force=force))
        report.extend(uninstall("codex", workspace, dry_run=dry_run, force=force))
        return report
    if target == "claude_code":
        return _uninstall_claude_code(dry_run=dry_run)
    if target == "cursor":
        return _uninstall_cursor(workspace, dry_run=dry_run, force=force)
    if target == "continue":
        return _uninstall_continue(dry_run=dry_run)
    if target == "codex":
        return _uninstall_codex(dry_run=dry_run)
    if target == "openai":
        return _uninstall_openai(workspace, dry_run=dry_run, force=force)
    raise ValueError(f"unknown target: {target}")


def _uninstall_claude_code(*, dry_run: bool) -> UninstallReport:
    home = Path(os.environ.get("CLAUDE_HOME", str(Path.home() / ".claude")))
    settings_path = home / "settings.json"
    return _remove_mcp_dict_key(settings_path, dry_run=dry_run, reader=_read_json, writer=_write_json)


def _uninstall_cursor(workspace: Path, *, dry_run: bool, force: bool) -> UninstallReport:
    home = Path(os.environ.get("CURSOR_HOME", str(Path.home() / ".cursor")))
    mcp_path = home / "mcp.json"
    report = _remove_mcp_dict_key(
        mcp_path, dry_run=dry_run, reader=_read_json, writer=_write_json
    )
    rule_path = workspace / ".cursor" / "rules" / "biobabel.md"
    _remove_workspace_file(
        rule_path,
        expected_text=_BIOBABEL_RULE,
        report=report,
        dry_run=dry_run,
        force=force,
    )
    return report


def _uninstall_continue(*, dry_run: bool) -> UninstallReport:
    home = Path(os.environ.get("CONTINUE_HOME", str(Path.home() / ".continue")))
    config_path = home / "config.yaml"
    report = UninstallReport()
    if not config_path.is_file():
        report.not_found.append(config_path)
        report.actions.append(f"· {config_path} (not found)")
        return report
    config = _read_yaml(config_path)
    servers = config.get("mcpServers")
    if not isinstance(servers, list):
        # Either missing or schema-divergent. Safe stance: report and skip,
        # don't rewrite a file whose shape we don't recognize.
        report.not_found.append(config_path)
        report.actions.append(
            f"· {config_path} (no 'mcpServers' list — biobabel not registered)"
        )
        return report
    new_servers = [
        s for s in servers
        if not (isinstance(s, dict) and s.get("name") == MCP_SERVER_KEY)
    ]
    if len(new_servers) == len(servers):
        report.not_found.append(config_path)
        report.actions.append(f"· {config_path} (no biobabel entry to remove)")
        return report
    config["mcpServers"] = new_servers
    if not dry_run:
        _write_yaml(config_path, config)
    report.removed.append(config_path)
    report.actions.append(
        f"{'DRY RUN — would remove' if dry_run else '+'} {config_path}"
        f" (mcpServers entry name='biobabel')"
    )
    return report


def _uninstall_codex(*, dry_run: bool) -> UninstallReport:
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    config_path = home / "config.toml"
    report = UninstallReport()
    if not config_path.is_file():
        report.not_found.append(config_path)
        report.actions.append(f"· {config_path} (not found)")
        return report
    doc = _read_toml(config_path)
    servers = doc.get("mcp_servers")
    if not isinstance(servers, Mapping) or MCP_SERVER_KEY not in servers:
        # Either missing or schema-divergent. Safe stance: report and skip,
        # don't rewrite a file whose shape we don't recognize.
        report.not_found.append(config_path)
        report.actions.append(
            f"· {config_path} (no mcp_servers.{MCP_SERVER_KEY} to remove)"
        )
        return report
    del servers[MCP_SERVER_KEY]
    if not dry_run:
        _write_toml(config_path, doc)
    report.removed.append(config_path)
    report.actions.append(
        f"{'DRY RUN — would remove' if dry_run else '+'} "
        f"{config_path} (mcp_servers.{MCP_SERVER_KEY})"
    )
    return report


def _uninstall_openai(workspace: Path, *, dry_run: bool, force: bool) -> UninstallReport:
    report = UninstallReport()
    _remove_workspace_file(
        workspace / "biobabel.tools.json",
        expected_text=_openai_tools_text(),
        report=report,
        dry_run=dry_run,
        force=force,
    )
    _remove_workspace_file(
        workspace / "biobabel.system_prompt.md",
        expected_text=_BIOBABEL_RULE,
        report=report,
        dry_run=dry_run,
        force=force,
    )
    return report


def _remove_mcp_dict_key(
    config_path: Path,
    *,
    dry_run: bool,
    reader,  # type: ignore[no-untyped-def]
    writer,  # type: ignore[no-untyped-def]
) -> UninstallReport:
    """Remove ``mcpServers.biobabel`` from a JSON-style config file."""
    report = UninstallReport()
    if not config_path.is_file():
        report.not_found.append(config_path)
        report.actions.append(f"· {config_path} (not found)")
        return report
    config = reader(config_path)
    servers = config.get("mcpServers")
    if not isinstance(servers, dict) or MCP_SERVER_KEY not in servers:
        report.not_found.append(config_path)
        report.actions.append(
            f"· {config_path} (no mcpServers.{MCP_SERVER_KEY} to remove)"
        )
        return report
    del servers[MCP_SERVER_KEY]
    if not dry_run:
        writer(config_path, config)
    report.removed.append(config_path)
    report.actions.append(
        f"{'DRY RUN — would remove' if dry_run else '+'} "
        f"{config_path} (mcpServers.{MCP_SERVER_KEY})"
    )
    return report


def _remove_workspace_file(
    path: Path,
    *,
    expected_text: str,
    report: UninstallReport,
    dry_run: bool,
    force: bool,
) -> None:
    """Delete a workspace artefact, but only if its content is unchanged.

    The "unchanged" test compares against what install would write today.
    A version skew between the recorded constant and the installed file
    therefore looks like a user modification — that false-positive errs on
    the side of preserving user data; ``--force`` overrides it.
    """
    if not path.is_file():
        report.not_found.append(path)
        report.actions.append(f"· {path} (not found)")
        return
    current = path.read_text(encoding="utf-8")
    if current != expected_text and not force:
        report.kept_modified.append(path)
        report.actions.append(
            f"~ {path} (kept — content modified; use --force to remove anyway)"
        )
        return
    if not dry_run:
        path.unlink()
    report.removed.append(path)
    report.actions.append(
        f"{'DRY RUN — would remove' if dry_run else '+'} {path}"
        + (" (modified, removed via --force)" if current != expected_text else "")
    )


# --- Rule text used by Cursor + openai prompt ----------------------------


_BIOBABEL_RULE = """# biobabel

biobabel is the read-only contract layer for the Bio-Babel ecosystem (R-to-Python
bioinformatics ports). When the user mentions ggplot2, monocle2py, monocle3,
pheatmap, ComplexHeatmap, grid_py, gtable, scales, etc., reach for the
biobabel.* MCP tools first instead of guessing the Python API from R memory.

Key tools:
- biobabel.list_packages()         — every registered package with triggers/tags/capabilities/not_when; rank yourself
- biobabel.search_contracts(query) — find relevant symbols, workflows, templates, concepts, and idioms
- biobabel.list_workflows(package) / describe_workflow(id) — reference multi-step workflows
- biobabel.describe_concept(id)    — Class B mental model (grid_py.Viewport, ...)
- biobabel.list_idioms(package)    — idiomatic patterns
- biobabel.describe_symbol(id)     — exact signature, parameters, state contract, and failure fixes
- biobabel.check_code(code)        — AST policy + anti-pattern lint of a snippet (does not run it)

Hard rule: if the user pastes R-style syntax (`library(`, `<-`, `%>%`,
`aes(displ, hwy)` without quotes), DO NOT translate line-by-line. Instead
call biobabel.describe_concept / describe_symbol / list_idioms to fetch the
Python API directly — the Python port may NOT mirror R 1:1.

biobabel does not infer intent, plan, or execute code for you. You plan from
the user's request and run code with your own tools; use biobabel to look up
exact package contracts and to lint snippets (check_code) before writing or
running them.
"""
