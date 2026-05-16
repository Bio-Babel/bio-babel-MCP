"""Installer tests: shape of files written for each --target."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from biobabel._exporters.installer import install


@pytest.fixture
def ide_homes(tmp_path, monkeypatch):
    """Redirect every IDE's config dir into tmp_path."""
    claude = tmp_path / "claude"
    cursor = tmp_path / "cursor"
    cont = tmp_path / "continue"
    monkeypatch.setenv("CLAUDE_HOME", str(claude))
    monkeypatch.setenv("CURSOR_HOME", str(cursor))
    monkeypatch.setenv("CONTINUE_HOME", str(cont))
    return {"claude": claude, "cursor": cursor, "continue": cont}


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


def test_all_target_installs_all_three(ide_homes, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    written = install("all", workspace=ws)
    paths_str = " ".join(str(p) for p in written)
    assert "claude" in paths_str
    assert "cursor" in paths_str
    assert "continue" in paths_str


def test_unknown_target_raises():
    with pytest.raises(ValueError, match="unknown target"):
        install("zed_editor", workspace=Path("/tmp/wsX"))
