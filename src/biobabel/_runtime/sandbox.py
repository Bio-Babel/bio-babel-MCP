"""Subprocess guardrail — the only execution mechanism.

This is a **guardrail against agent mistakes, not a security boundary**.
See `docs/governance/ADRs/0006-sandbox-guardrail-not-isolation.md`.

In scope:
- AST safety scan blocks obvious destructive imports/calls (os, subprocess,
  eval, open, ...) before launch.
- rlimits via preexec_fn cap CPU time, address space, file write size, and
  open file descriptors. Linux: bound. macOS: best-effort (RLIMIT_AS does
  not bind RSS — surfaced as a startup warning).
- cwd = session workspace; relative writes land there.
- timeout enforced via subprocess.Popen.communicate.
- stdout/stderr captured and truncated.

Out of scope (by design — would require real isolation: nsjail / firejail /
bubblewrap, all OS-specific):
- Absolute-path FS reads via allowlisted libraries (pathlib, pandas, numpy).
  Same accepted-risk class as `biobabel.load_adata(path=...)`.
- Compromised upstream packages (their `_biobabel/__init__.py` runs at
  registry-build time, *before* this guardrail is in the picture).
- Adversarial prompt injection that constructs forbidden symbols via
  obfuscation (e.g. `getattr(builtins, "ev"+"al")`).
"""

from __future__ import annotations

import hashlib
import os
import platform
import resource
import subprocess
import sys
import textwrap
import time
import warnings
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


# Keep this tuple in sync with the setrlimit calls in `_make_rlimit_preexec`.
# `_ensure_rlimit_support` probes each entry at first use; a missing constant
# raises loudly so the user knows the host is unsupported.
_REQUIRED_RLIMITS: tuple[str, ...] = (
    "RLIMIT_AS",
    "RLIMIT_CPU",
    "RLIMIT_FSIZE",
    "RLIMIT_NOFILE",
    "RLIMIT_CORE",
)

_rlimit_support_checked = False


def _ensure_rlimit_support() -> None:
    """Verify the host can apply the rlimits this module relies on.

    Called lazily on the first ``run_code`` invocation per process. Failures
    here are deliberately loud — the developer needs to know up front that
    the guardrail is degraded or absent on their platform, not at some
    later point when a runaway process eats their RAM.
    """
    global _rlimit_support_checked
    if _rlimit_support_checked:
        return

    if not hasattr(resource, "setrlimit"):
        raise RuntimeError(
            "biobabel runtime requires POSIX resource.setrlimit; "
            f"platform={platform.system()} does not provide it. "
            "biobabel-mcp execution path is not supported on this OS."
        )

    for name in _REQUIRED_RLIMITS:
        if not hasattr(resource, name):
            raise RuntimeError(
                f"biobabel runtime requires resource.{name}; not present on "
                f"this build ({platform.system()} / {sys.version_info})."
            )
        rnum = getattr(resource, name)
        current = resource.getrlimit(rnum)
        # No-op probe: re-set to current value. Raises if the API is broken
        # in some unexpected way; succeeds otherwise without changing state.
        resource.setrlimit(rnum, current)

    if sys.platform == "darwin":
        warnings.warn(
            "biobabel runtime: on macOS, RLIMIT_AS does not bind RSS, so the "
            "memory guardrail is best-effort. CPU time, file size, and nofile "
            "limits remain enforced. Use Linux for binding memory limits. "
            "(See docs/governance/ADRs/0006-sandbox-guardrail-not-isolation.md.)",
            stacklevel=3,
        )

    _rlimit_support_checked = True


def _make_rlimit_preexec(limits: RuntimeLimits):
    """Build the preexec_fn that applies rlimits in the forked child.

    No try/except: a setrlimit failure here means the requested limit
    exceeds the host's hard cap (EPERM), or a constant from
    ``_REQUIRED_RLIMITS`` is missing. Both are conditions the user must
    see — Popen surfaces them via its preexec failure pipe rather than
    silently launching an un-bounded child.
    """
    mem_bytes = limits.max_memory_mb * 1024 * 1024
    fsize_bytes = limits.max_output_file_mb * 1024 * 1024

    def _apply() -> None:
        resource.setrlimit(resource.RLIMIT_AS,     (mem_bytes, mem_bytes))
        resource.setrlimit(resource.RLIMIT_CPU,    (limits.hard_timeout_s, limits.hard_timeout_s))
        resource.setrlimit(resource.RLIMIT_FSIZE,  (fsize_bytes, fsize_bytes))
        resource.setrlimit(resource.RLIMIT_NOFILE, (limits.max_open_files, limits.max_open_files))
        resource.setrlimit(resource.RLIMIT_CORE,   (0, 0))

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
    """Execute *code* in a guarded subprocess.

    Not a security boundary — see this module's docstring.
    """
    _ensure_rlimit_support()
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
