"""Subprocess sandbox — the only execution mechanism.

Hardening:
- AST safety scan before launch
- rlimits via preexec_fn (CPU, AS memory, file size, nofile) on POSIX
- empty network env (`BIOBABEL_NETWORK_DENY=1`, `MPLBACKEND=Agg`)
- cwd = session workspace, only the workspace is writable
- timeout enforced via subprocess.Popen.communicate
- stdout/stderr captured + truncated
"""

from __future__ import annotations

import hashlib
import os
import resource
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path

from biobabel._runtime.limits import RuntimeLimits
from biobabel._runtime.policy import CodeScanResult, scan_code


@dataclass
class SandboxResult:
    ok: bool
    stdout: str
    stderr: str
    return_code: int
    duration_ms: float
    scan: CodeScanResult
    timed_out: bool = False
    new_files: list[Path] = field(default_factory=list)
    code_hash: str = ""
    error_code: str = ""


def _make_rlimit_preexec(limits: RuntimeLimits):
    def _apply() -> None:
        mem_bytes = limits.max_memory_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        except (ValueError, OSError):
            pass
        try:
            resource.setrlimit(
                resource.RLIMIT_CPU,
                (limits.hard_timeout_s, limits.hard_timeout_s),
            )
        except (ValueError, OSError):
            pass
        try:
            file_bytes = limits.max_output_file_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_FSIZE, (file_bytes, file_bytes))
        except (ValueError, OSError):
            pass
        try:
            resource.setrlimit(
                resource.RLIMIT_NOFILE,
                (limits.max_open_files, limits.max_open_files),
            )
        except (ValueError, OSError):
            pass
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except (ValueError, OSError):
            pass

    return _apply


def _filter_env() -> dict[str, str]:
    keep = {"PATH", "HOME", "LANG", "LC_ALL", "PYTHONPATH", "TMPDIR"}
    return {k: v for k, v in os.environ.items() if k in keep}


def _wrap(code: str, workspace: Path) -> str:
    return textwrap.dedent(
        f"""
        import os, sys
        os.chdir({str(workspace)!r})
        # Force matplotlib non-interactive
        os.environ.setdefault("MPLBACKEND", "Agg")
        __biobabel_user_code__ = compile({code!r}, "<biobabel-sandbox>", "exec")
        exec(__biobabel_user_code__, {{"__name__": "__main__"}})
        """
    ).strip()


def run_code(
    code: str,
    workspace: Path,
    *,
    limits: RuntimeLimits | None = None,
    timeout_s: int | None = None,
    extra_allow_imports: list[str] | None = None,
) -> SandboxResult:
    """Execute *code* in a hardened subprocess."""
    limits = limits or RuntimeLimits()
    timeout = min(timeout_s or limits.default_timeout_s, limits.hard_timeout_s)

    code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    scan = scan_code(code, extra_allow=extra_allow_imports or ())
    if not scan.ok:
        return SandboxResult(
            ok=False,
            stdout="",
            stderr="\n".join(f"line {v.line}: {v.kind}: {v.detail}" for v in scan.violations),
            return_code=-1,
            duration_ms=0.0,
            scan=scan,
            code_hash=code_hash,
            error_code="security_violation",
        )

    workspace.mkdir(parents=True, exist_ok=True)
    pre_files = {p for p in workspace.rglob("*") if p.is_file()}

    env = _filter_env()
    env["MPLBACKEND"] = "Agg"
    env["BIOBABEL_NETWORK_DENY"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    wrapper = _wrap(code, workspace)

    preexec = _make_rlimit_preexec(limits) if os.name == "posix" else None

    start = time.perf_counter()
    timed_out = False
    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", wrapper],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(workspace),
            env=env,
            preexec_fn=preexec,
        )
        try:
            stdout_b, stderr_b = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            stdout_b, stderr_b = proc.communicate()
        return_code = proc.returncode
    except OSError as exc:
        elapsed = (time.perf_counter() - start) * 1000
        return SandboxResult(
            ok=False,
            stdout="",
            stderr=f"sandbox launch failed: {exc!r}",
            return_code=-1,
            duration_ms=elapsed,
            scan=scan,
            code_hash=code_hash,
            error_code="sandbox_launch_failed",
        )

    duration_ms = (time.perf_counter() - start) * 1000
    max_chars = limits.max_stdout_kb * 1024
    stdout = stdout_b.decode("utf-8", errors="replace")[:max_chars]
    stderr = stderr_b.decode("utf-8", errors="replace")[:max_chars]

    new_files = sorted(
        {p for p in workspace.rglob("*") if p.is_file()} - pre_files
    )

    ok = return_code == 0 and not timed_out
    error_code = ""
    if timed_out:
        error_code = "timeout"
    elif return_code != 0:
        error_code = "non_zero_exit"

    return SandboxResult(
        ok=ok,
        stdout=stdout,
        stderr=stderr,
        return_code=return_code,
        duration_ms=duration_ms,
        scan=scan,
        timed_out=timed_out,
        new_files=new_files,
        code_hash=code_hash,
        error_code=error_code,
    )
