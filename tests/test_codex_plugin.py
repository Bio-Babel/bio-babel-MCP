"""Codex plugin bundle: structural invariants + hook I/O contract.

Codex's plugin format differs from Claude Code's in ways that are easy to get
wrong (manifest must declare paths explicitly, hooks.json has an extra `hooks`
nesting level and no matcher, the hook output is `hookSpecificOutput`). These
tests pin the differences so a blind copy of the Claude bundle would fail.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN = REPO_ROOT / "plugin" / "biobabel-codex"
HOOK = PLUGIN / "hooks" / "r-paste-detector.py"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_manifest_lives_in_codex_plugin_dir_and_declares_paths():
    manifest = _load(PLUGIN / ".codex-plugin" / "plugin.json")
    assert manifest["name"] == "biobabel"
    # Codex (unlike Claude) requires the manifest to point at each surface.
    for key, rel in [
        ("skills", "skills/"),
        ("mcpServers", ".mcp.json"),
        ("hooks", "hooks/hooks.json"),
    ]:
        val = manifest[key]
        assert val.startswith("./"), f"{key} must be a relative ./ path"
        target = val[len("./"):]
        assert target == rel
        assert (PLUGIN / target).exists(), f"{key} -> {target} missing"


def test_mcp_json_uses_mcpservers_wrapper():
    mcp = _load(PLUGIN / ".mcp.json")
    # Verified against real Codex plugins: camelCase wrapper, like Claude.
    assert mcp["mcpServers"]["biobabel"]["command"] == "biobabel-mcp"
    assert mcp["mcpServers"]["biobabel"]["args"] == []


def test_hooks_json_has_codex_nested_shape():
    hooks = _load(PLUGIN / "hooks" / "hooks.json")
    entries = hooks["hooks"]["UserPromptSubmit"]
    assert isinstance(entries, list) and len(entries) == 1
    # Codex nests an inner `hooks` array (Claude puts command at the top level).
    inner = entries[0]["hooks"]
    assert inner[0]["type"] == "command"
    cmd = inner[0]["command"]
    assert "${PLUGIN_ROOT}" in cmd          # Codex var, not CLAUDE_PLUGIN_ROOT
    assert "CLAUDE_PLUGIN_ROOT" not in cmd
    assert cmd.endswith("hooks/r-paste-detector.py")
    # UserPromptSubmit ignores matcher in Codex; we must not set one.
    assert "matcher" not in entries[0]


def test_marketplace_points_at_codex_bundle():
    mp = _load(REPO_ROOT / ".agents" / "plugins" / "marketplace.json")
    entry = mp["plugins"][0]
    assert entry["name"] == "biobabel"
    assert entry["source"]["source"] == "local"
    path = entry["source"]["path"]
    assert (REPO_ROOT / path).resolve() == PLUGIN
    assert (REPO_ROOT / path / ".codex-plugin" / "plugin.json").exists()


def test_skills_are_present_with_frontmatter():
    skill_dirs = sorted(p.name for p in (PLUGIN / "skills").iterdir() if p.is_dir())
    assert "biobabel-overview" in skill_dirs
    for name in skill_dirs:
        text = (PLUGIN / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        assert text.startswith("---"), f"{name}: missing frontmatter"
        assert "name:" in text and "description:" in text


def _run_hook(prompt: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"prompt": prompt}),
        capture_output=True,
        text=True,
    )


def test_hook_emits_codex_additional_context_on_r_syntax():
    res = _run_hook("cds <- library(monocle3)")
    assert res.returncode == 0
    out = json.loads(res.stdout)
    # Codex output contract — NOT Claude's {"decision","context"}.
    block = out["hookSpecificOutput"]
    assert block["hookEventName"] == "UserPromptSubmit"
    assert "biobabel" in block["additionalContext"]
    assert "decision" not in out


def test_hook_recognizes_ggplot_aes():
    res = _run_hook("ggplot(df, aes(x, y)) + geom_point()")
    out = json.loads(res.stdout)
    assert "ggplot2_py" in out["hookSpecificOutput"]["additionalContext"]


def test_hook_is_silent_on_plain_prompt():
    res = _run_hook("please summarize this dataframe for me")
    assert res.returncode == 0
    assert res.stdout.strip() == ""


def test_hook_exits_zero_on_garbage_stdin():
    res = subprocess.run(
        [sys.executable, str(HOOK)], input="not json", capture_output=True, text=True
    )
    assert res.returncode == 0
    assert res.stdout.strip() == ""


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
