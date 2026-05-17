"""Subprocess sandbox: success/error/timeout/security paths."""

from __future__ import annotations

import sys

import pytest

from biobabel._runtime.limits import RuntimeLimits
from biobabel._runtime.sandbox import run_code

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="rlimits POSIX-only")


def test_run_print(tmp_path):
    res = run_code("print('hi from sandbox')", tmp_path)
    assert res.ok, res.stderr
    assert "hi from sandbox" in res.stdout


def test_artifact_written(tmp_path):
    code = "from pathlib import Path; Path('out.txt').write_text('hello')"
    res = run_code(code, tmp_path)
    assert res.ok, res.stderr
    written = {p.name for p in res.new_files}
    assert "out.txt" in written


def test_security_violation_blocks_subprocess(tmp_path):
    res = run_code("import subprocess\nsubprocess.run(['ls'])", tmp_path)
    assert not res.ok
    assert res.error_code == "security_violation"


def test_timeout(tmp_path):
    limits = RuntimeLimits(default_timeout_s=1, hard_timeout_s=2)
    code = "import time; time.sleep(5)"
    # `time` is allowed, so it bypasses AST scan.
    res = run_code(code, tmp_path, limits=limits, timeout_s=1)
    assert not res.ok
    assert res.error_code == "timeout"


def test_ensure_rlimit_support_runs_on_supported_host():
    """The startup probe replaces the previous silent try/except around
    setrlimit. On a supported POSIX host it must succeed loudly — no
    fallback path, no silent skip.

    Linux: passes; macOS: emits a warning then passes; Windows: raises
    RuntimeError (filtered out by the module pytestmark above).
    """
    from biobabel._runtime import sandbox

    # Reset the module flag so we actually re-run the probe in this test.
    sandbox._rlimit_support_checked = False
    sandbox._ensure_rlimit_support()
    assert sandbox._rlimit_support_checked is True
