"""Subprocess sandbox: success/error/timeout/security paths + streaming."""

from __future__ import annotations

import sys

import pytest

from biobabel._runtime.limits import RuntimeLimits
from biobabel._runtime.sandbox import StreamChunk, run_code

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


# --- streaming (P2-3) ----------------------------------------------------


def test_on_progress_receives_stdout_chunks(tmp_path):
    chunks: list[StreamChunk] = []
    res = run_code(
        "print('line one')\nprint('line two')",
        tmp_path,
        on_progress=chunks.append,
    )
    assert res.ok, res.stderr
    texts = "".join(c.text for c in chunks if c.stream == "stdout")
    assert "line one" in texts
    assert "line two" in texts


def test_on_progress_receives_stderr_chunks(tmp_path):
    """``raise`` triggers Python's default traceback printer, which writes
    to stderr before exit. That gives a stderr-bearing sandbox run without
    requiring ``import sys`` (denied by the AST policy)."""
    chunks: list[StreamChunk] = []
    res = run_code(
        "raise ValueError('boom')",
        tmp_path,
        on_progress=chunks.append,
    )
    assert not res.ok  # non-zero exit from raise
    stderr_texts = "".join(c.text for c in chunks if c.stream == "stderr")
    assert "ValueError" in stderr_texts
    assert "boom" in stderr_texts


def test_on_progress_emits_progressively_before_exit(tmp_path):
    """Chunks must arrive while the subprocess is still alive, not held
    until exit. With ``python -u`` + PYTHONUNBUFFERED the child flushes
    each ``print`` immediately; the parent's selector loop should observe
    arrivals one at a time."""
    import time as _time

    timestamps: list[float] = []
    # ``import sys`` is denied by policy; use plain ``print(flush=True)``
    # — that's why the parent sees each line as the child writes it.
    code = (
        "import time\n"
        "for i in range(4):\n"
        "    print(f'step {i}', flush=True)\n"
        "    time.sleep(0.2)\n"
    )
    start = _time.perf_counter()

    def _record(_chunk: StreamChunk) -> None:
        timestamps.append(_time.perf_counter() - start)

    res = run_code(code, tmp_path, on_progress=_record)
    assert res.ok, res.stderr
    # Total runtime ≈ 0.8s. At least one chunk must arrive before 0.6s —
    # otherwise streaming is silently a batch with extra steps.
    assert any(t < 0.6 for t in timestamps), (
        f"expected at least one chunk before 0.6s; got {timestamps}"
    )


def test_on_progress_flushes_trailing_no_newline_fragment(tmp_path):
    """A program that writes without a trailing ``\\n`` still has its
    last partial line surfaced as a chunk at EOF — never silently
    dropped. ``print(..., end='', flush=True)`` exercises this without
    needing ``import sys``."""
    chunks: list[StreamChunk] = []
    res = run_code(
        "print('no-newline-here', end='', flush=True)",
        tmp_path,
        on_progress=chunks.append,
    )
    assert res.ok, res.stderr
    stdout_texts = "".join(c.text for c in chunks if c.stream == "stdout")
    assert "no-newline-here" in stdout_texts


def test_on_progress_none_keeps_legacy_batch_behavior(tmp_path):
    """When no callback is passed, run_code is equivalent to the old
    batch shape: full stdout/stderr captured, no callbacks of any kind."""
    res = run_code("print('hi')", tmp_path, on_progress=None)
    assert res.ok
    assert "hi" in res.stdout


def test_streaming_with_timeout_emits_some_chunks_then_kills(tmp_path):
    """Timeout path must still emit chunks that arrived BEFORE the kill,
    rather than dropping everything because of the wall-clock fail. The
    final SandboxResult marks timed_out=True."""
    chunks: list[StreamChunk] = []
    limits = RuntimeLimits(default_timeout_s=2, hard_timeout_s=2)
    code = (
        "import time\n"
        "for i in range(20):\n"
        "    print(f'tick {i}', flush=True)\n"
        "    time.sleep(0.2)\n"
    )
    res = run_code(
        code, tmp_path, limits=limits, timeout_s=1, on_progress=chunks.append
    )
    assert not res.ok
    assert res.error_code == "timeout"
    assert res.timed_out
    # At least one chunk should have made it through before the kill.
    assert len(chunks) >= 1, "timeout path must not drop all in-flight output"


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
