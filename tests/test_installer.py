"""Installer tests: shape of files written for each --target."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import tomlkit
import yaml

from biobabel._exporters.installer import install, uninstall


@pytest.fixture
def ide_homes(tmp_path, monkeypatch):
    """Redirect every IDE's config dir into tmp_path."""
    claude = tmp_path / "claude"
    cursor = tmp_path / "cursor"
    cont = tmp_path / "continue"
    codex = tmp_path / "codex"
    monkeypatch.setenv("CLAUDE_HOME", str(claude))
    monkeypatch.setenv("CURSOR_HOME", str(cursor))
    monkeypatch.setenv("CONTINUE_HOME", str(cont))
    monkeypatch.setenv("CODEX_HOME", str(codex))
    return {"claude": claude, "cursor": cursor, "continue": cont, "codex": codex}


def test_claude_code_writes_settings_json(ide_homes):
    written = install("claude_code", workspace=Path("/tmp/wsX"))
    assert len(written) == 1
    settings = json.loads(written[0].read_text())
    assert "mcpServers" in settings
    assert settings["mcpServers"]["biobabel"]["command"] == "biobabel-mcp"
    assert settings["mcpServers"]["biobabel"]["args"] == []


def test_claude_code_preserves_existing_servers(ide_homes):
    home = ide_homes["claude"]
    home.mkdir()
    (home / "settings.json").write_text(
        json.dumps({"mcpServers": {"other": {"command": "other-mcp"}}, "theme": "dark"})
    )
    install("claude_code", workspace=Path("/tmp/wsX"))
    settings = json.loads((home / "settings.json").read_text())
    assert settings["theme"] == "dark"
    assert "other" in settings["mcpServers"]
    assert "biobabel" in settings["mcpServers"]


def test_claude_code_is_idempotent(ide_homes):
    install("claude_code", workspace=Path("/tmp/wsX"))
    before = (ide_homes["claude"] / "settings.json").read_text()
    install("claude_code", workspace=Path("/tmp/wsX"))
    after = (ide_homes["claude"] / "settings.json").read_text()
    assert before == after


def test_cursor_writes_mcp_json_and_workspace_rule(ide_homes, tmp_path):
    ws = tmp_path / "myproject"
    ws.mkdir()
    written = install("cursor", workspace=ws)
    assert len(written) == 2
    mcp = json.loads((ide_homes["cursor"] / "mcp.json").read_text())
    assert mcp["mcpServers"]["biobabel"]["command"] == "biobabel-mcp"
    rule = (ws / ".cursor" / "rules" / "biobabel.md").read_text()
    assert "biobabel.describe_concept" in rule
    assert "biobabel.scaffold" not in rule       # removed scaffolds
    assert "biobabel.r_translate" not in rule    # removed R→Py translation


def test_continue_writes_yaml_mcp_servers_list(ide_homes):
    written = install("continue", workspace=Path("/tmp/wsX"))
    assert len(written) == 1
    config = yaml.safe_load(written[0].read_text())
    assert isinstance(config["mcpServers"], list)
    entries = [s for s in config["mcpServers"] if s.get("name") == "biobabel"]
    assert len(entries) == 1
    assert entries[0]["command"] == "biobabel-mcp"


def test_continue_is_idempotent(ide_homes):
    install("continue", workspace=Path("/tmp/wsX"))
    install("continue", workspace=Path("/tmp/wsX"))
    config = yaml.safe_load((ide_homes["continue"] / "config.yaml").read_text())
    entries = [s for s in config["mcpServers"] if s.get("name") == "biobabel"]
    assert len(entries) == 1  # not duplicated


def test_continue_preserves_other_servers(ide_homes):
    cont = ide_homes["continue"]
    cont.mkdir()
    (cont / "config.yaml").write_text(yaml.safe_dump({
        "models": [{"name": "claude"}],
        "mcpServers": [{"name": "other-mcp", "command": "other"}],
    }))
    install("continue", workspace=Path("/tmp/wsX"))
    config = yaml.safe_load((cont / "config.yaml").read_text())
    names = {s["name"] for s in config["mcpServers"]}
    assert names == {"other-mcp", "biobabel"}
    assert config["models"] == [{"name": "claude"}]


def test_continue_rejects_malformed_existing_field(ide_homes):
    cont = ide_homes["continue"]
    cont.mkdir()
    (cont / "config.yaml").write_text(yaml.safe_dump({
        "mcpServers": "this should have been a list",
    }))
    with pytest.raises(RuntimeError, match="must be a list"):
        install("continue", workspace=Path("/tmp/wsX"))


def test_codex_writes_config_toml(ide_homes):
    written = install("codex", workspace=Path("/tmp/wsX"))
    assert len(written) == 1
    assert written[0].name == "config.toml"
    doc = tomlkit.parse(written[0].read_text())
    assert doc["mcp_servers"]["biobabel"]["command"] == "biobabel-mcp"
    assert list(doc["mcp_servers"]["biobabel"]["args"]) == []


def test_codex_preserves_existing_config_and_comments(ide_homes):
    home = ide_homes["codex"]
    home.mkdir()
    (home / "config.toml").write_text(
        '# my codex config\nmodel = "o3"\n\n[mcp_servers.other]\ncommand = "other"\n'
    )
    install("codex", workspace=Path("/tmp/wsX"))
    text = (home / "config.toml").read_text()
    assert "# my codex config" in text          # comment survives
    doc = tomlkit.parse(text)
    assert doc["model"] == "o3"
    assert "other" in doc["mcp_servers"]
    assert "biobabel" in doc["mcp_servers"]


def test_codex_is_idempotent(ide_homes):
    install("codex", workspace=Path("/tmp/wsX"))
    before = (ide_homes["codex"] / "config.toml").read_text()
    install("codex", workspace=Path("/tmp/wsX"))
    after = (ide_homes["codex"] / "config.toml").read_text()
    assert before == after


def test_codex_rejects_malformed_mcp_servers_field(ide_homes):
    home = ide_homes["codex"]
    home.mkdir()
    (home / "config.toml").write_text('mcp_servers = "this should have been a table"\n')
    with pytest.raises(RuntimeError, match="must be a table"):
        install("codex", workspace=Path("/tmp/wsX"))


def test_all_target_installs_every_ide(ide_homes, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    written = install("all", workspace=ws)
    paths_str = " ".join(str(p) for p in written)
    assert "claude" in paths_str
    assert "cursor" in paths_str
    assert "continue" in paths_str
    assert "codex" in paths_str


def test_unknown_target_raises():
    with pytest.raises(ValueError, match="unknown target"):
        install("zed_editor", workspace=Path("/tmp/wsX"))


# --- Uninstall coverage ----------------------------------------------------
#
# Each install path has a symmetric uninstall path. The tests below verify:
# - the biobabel entry is removed
# - the user's other keys/servers/files are NOT removed
# - re-running uninstall on a clean state is a no-op (not an error)
# - workspace artefacts (cursor rule, openai files) are preserved when
#   user-modified, removed under --force
# - dry-run produces the same report without touching disk


def test_uninstall_claude_code_removes_biobabel_key(ide_homes):
    install("claude_code", workspace=Path("/tmp/wsX"))
    report = uninstall("claude_code", workspace=Path("/tmp/wsX"))
    settings = json.loads((ide_homes["claude"] / "settings.json").read_text())
    assert "biobabel" not in settings.get("mcpServers", {})
    assert len(report.removed) == 1


def test_uninstall_claude_code_preserves_other_servers_and_keys(ide_homes):
    home = ide_homes["claude"]
    home.mkdir()
    (home / "settings.json").write_text(
        json.dumps({
            "mcpServers": {
                "other": {"command": "other-mcp"},
                "biobabel": {"command": "biobabel-mcp"},
            },
            "theme": "dark",
        })
    )
    uninstall("claude_code", workspace=Path("/tmp/wsX"))
    settings = json.loads((home / "settings.json").read_text())
    assert "biobabel" not in settings["mcpServers"]
    assert "other" in settings["mcpServers"]
    assert settings["theme"] == "dark"


def test_uninstall_claude_code_idempotent_on_fresh_state(ide_homes):
    """Uninstall on a never-installed env reports not_found rather than crashing."""
    report = uninstall("claude_code", workspace=Path("/tmp/wsX"))
    assert report.removed == []
    assert len(report.not_found) == 1


def test_uninstall_cursor_removes_global_config_and_unmodified_rule(ide_homes, tmp_path):
    ws = tmp_path / "myproj"
    ws.mkdir()
    install("cursor", workspace=ws)
    rule = ws / ".cursor" / "rules" / "biobabel.md"
    assert rule.is_file()

    uninstall("cursor", workspace=ws)

    mcp = json.loads((ide_homes["cursor"] / "mcp.json").read_text())
    assert "biobabel" not in mcp.get("mcpServers", {})
    assert not rule.exists()


def test_uninstall_cursor_preserves_user_modified_rule(ide_homes, tmp_path):
    """If the user appended their own notes to the rule file, uninstall must
    NOT silently delete their edits. They get a kept_modified report entry."""
    ws = tmp_path / "myproj"
    ws.mkdir()
    install("cursor", workspace=ws)
    rule = ws / ".cursor" / "rules" / "biobabel.md"
    rule.write_text(rule.read_text() + "\n\n# my custom rules\n")

    report = uninstall("cursor", workspace=ws)

    assert rule.exists()
    assert "my custom rules" in rule.read_text()
    assert rule in report.kept_modified


def test_uninstall_cursor_force_removes_modified_rule(ide_homes, tmp_path):
    ws = tmp_path / "myproj"
    ws.mkdir()
    install("cursor", workspace=ws)
    rule = ws / ".cursor" / "rules" / "biobabel.md"
    rule.write_text("MODIFIED")

    uninstall("cursor", workspace=ws, force=True)

    assert not rule.exists()


def test_uninstall_continue_removes_biobabel_entry(ide_homes):
    install("continue", workspace=Path("/tmp/wsX"))
    uninstall("continue", workspace=Path("/tmp/wsX"))
    config = yaml.safe_load((ide_homes["continue"] / "config.yaml").read_text())
    entries = [s for s in config.get("mcpServers", []) if s.get("name") == "biobabel"]
    assert entries == []


def test_uninstall_continue_preserves_other_entries_and_top_level_keys(ide_homes):
    home = ide_homes["continue"]
    home.mkdir()
    (home / "config.yaml").write_text(yaml.safe_dump({
        "models": [{"name": "claude"}],
        "mcpServers": [
            {"name": "biobabel", "command": "biobabel-mcp"},
            {"name": "other-mcp", "command": "other"},
        ],
    }))
    uninstall("continue", workspace=Path("/tmp/wsX"))
    config = yaml.safe_load((home / "config.yaml").read_text())
    names = {s["name"] for s in config["mcpServers"]}
    assert names == {"other-mcp"}
    assert config["models"] == [{"name": "claude"}]


def test_uninstall_continue_tolerates_malformed_mcp_servers_field(ide_homes):
    """Install rejects a malformed field; uninstall must NOT rewrite a file
    whose shape it doesn't recognize — instead it reports not_found and exits
    cleanly so the user can investigate."""
    home = ide_homes["continue"]
    home.mkdir()
    (home / "config.yaml").write_text(yaml.safe_dump({
        "mcpServers": "this should have been a list",
    }))
    report = uninstall("continue", workspace=Path("/tmp/wsX"))
    assert report.removed == []
    assert (home / "config.yaml") in report.not_found
    # The malformed file is untouched.
    assert yaml.safe_load((home / "config.yaml").read_text())["mcpServers"] == \
        "this should have been a list"


def test_uninstall_codex_removes_biobabel_table(ide_homes):
    install("codex", workspace=Path("/tmp/wsX"))
    report = uninstall("codex", workspace=Path("/tmp/wsX"))
    doc = tomlkit.parse((ide_homes["codex"] / "config.toml").read_text())
    assert "biobabel" not in doc.get("mcp_servers", {})
    assert len(report.removed) == 1


def test_uninstall_codex_preserves_other_servers_and_keys(ide_homes):
    home = ide_homes["codex"]
    home.mkdir()
    (home / "config.toml").write_text(
        'model = "o3"\n\n'
        '[mcp_servers.biobabel]\ncommand = "biobabel-mcp"\nargs = []\n\n'
        '[mcp_servers.other]\ncommand = "other"\n'
    )
    uninstall("codex", workspace=Path("/tmp/wsX"))
    doc = tomlkit.parse((home / "config.toml").read_text())
    assert "biobabel" not in doc["mcp_servers"]
    assert "other" in doc["mcp_servers"]
    assert doc["model"] == "o3"


def test_uninstall_codex_idempotent_on_fresh_state(ide_homes):
    report = uninstall("codex", workspace=Path("/tmp/wsX"))
    assert report.removed == []
    assert len(report.not_found) == 1


def test_uninstall_openai_removes_unmodified_workspace_files(tmp_path):
    ws = tmp_path / "wsX"
    ws.mkdir()
    install("openai", workspace=ws)
    uninstall("openai", workspace=ws)
    assert not (ws / "biobabel.tools.json").exists()
    assert not (ws / "biobabel.system_prompt.md").exists()


def test_uninstall_openai_preserves_modified_prompt(tmp_path):
    ws = tmp_path / "wsX"
    ws.mkdir()
    install("openai", workspace=ws)
    (ws / "biobabel.system_prompt.md").write_text("EDITED BY USER")
    report = uninstall("openai", workspace=ws)
    assert (ws / "biobabel.system_prompt.md").exists()
    # tools.json is unmodified → still removed
    assert not (ws / "biobabel.tools.json").exists()
    assert (ws / "biobabel.system_prompt.md") in report.kept_modified


def test_uninstall_all_runs_every_ide_target_and_skips_openai(ide_homes, tmp_path):
    """Symmetric with install("all", ...) — IDE targets, openai opt-in."""
    ws = tmp_path / "wsX"
    ws.mkdir()
    install("all", workspace=ws)
    install("openai", workspace=ws)   # opt-in install, should NOT be undone by uninstall("all", ...)

    uninstall("all", workspace=ws)

    # IDE configs cleaned
    settings = json.loads((ide_homes["claude"] / "settings.json").read_text())
    assert "biobabel" not in settings.get("mcpServers", {})
    cursor_cfg = json.loads((ide_homes["cursor"] / "mcp.json").read_text())
    assert "biobabel" not in cursor_cfg.get("mcpServers", {})
    cont_cfg = yaml.safe_load((ide_homes["continue"] / "config.yaml").read_text())
    assert [s for s in cont_cfg.get("mcpServers", []) if s.get("name") == "biobabel"] == []
    codex_cfg = tomlkit.parse((ide_homes["codex"] / "config.toml").read_text())
    assert "biobabel" not in codex_cfg.get("mcp_servers", {})

    # openai workspace files NOT cleaned (target opted out)
    assert (ws / "biobabel.tools.json").exists()
    assert (ws / "biobabel.system_prompt.md").exists()


def test_uninstall_dry_run_does_not_modify_files(ide_homes):
    install("claude_code", workspace=Path("/tmp/wsX"))
    before = (ide_homes["claude"] / "settings.json").read_text()
    report = uninstall("claude_code", workspace=Path("/tmp/wsX"), dry_run=True)
    after = (ide_homes["claude"] / "settings.json").read_text()
    assert before == after
    # report still describes what WOULD have happened
    assert len(report.removed) == 1
    assert any("DRY RUN" in line for line in report.actions)


def test_uninstall_unknown_target_raises():
    with pytest.raises(ValueError, match="unknown target"):
        uninstall("zed_editor", workspace=Path("/tmp/wsX"))
