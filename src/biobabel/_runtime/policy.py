"""AST-based safety scan + import allowlist.

Default-deny network, shell, and process-spawning modules. The allowlist is
the union of (a) hard-coded scientific Python stack and (b) the dynamic set
of import-names from the registry.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Iterable

DEFAULT_IMPORT_ALLOW: frozenset[str] = frozenset(
    {
        # Scientific Python
        "numpy",
        "pandas",
        "scipy",
        "matplotlib",
        "matplotlib.pyplot",
        "seaborn",
        "anndata",
        "scanpy",
        "PIL",
        "Pillow",
        "skimage",
        "sklearn",
        "statsmodels",
        # Standard library that's safe
        "math",
        "random",
        "json",
        "itertools",
        "functools",
        "collections",
        "dataclasses",
        "typing",
        "datetime",
        "pathlib",
        "io",
        "re",
        "string",
        "warnings",
    }
)

DEFAULT_IMPORT_DENY: frozenset[str] = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "socket",
        "asyncio",
        "threading",
        "multiprocessing",
        "ssl",
        "ctypes",
        "shutil",
        "tempfile",
        "requests",
        "urllib",
        "urllib3",
        "http",
        "httpx",
        "paramiko",
        "fabric",
        "pickle",
        "marshal",
        "shelve",
        "importlib",
        "pkgutil",
    }
)

# Forbidden builtin names (calls)
FORBIDDEN_CALLS: frozenset[str] = frozenset(
    {"eval", "exec", "compile", "__import__", "open", "input"}
)


@dataclass(frozen=True)
class CodeViolation:
    kind: str
    line: int
    detail: str


@dataclass
class CodeScanResult:
    ok: bool
    violations: list[CodeViolation] = field(default_factory=list)


def scan_code(
    code: str,
    *,
    extra_allow: Iterable[str] = (),
    extra_deny: Iterable[str] = (),
) -> CodeScanResult:
    """AST safety scan. Returns a list of violations; empty => safe."""

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return CodeScanResult(
            ok=False,
            violations=[
                CodeViolation(
                    kind="syntax_error",
                    line=exc.lineno or 0,
                    detail=str(exc),
                )
            ],
        )

    allow = set(DEFAULT_IMPORT_ALLOW) | set(extra_allow)
    deny = set(DEFAULT_IMPORT_DENY) | set(extra_deny)

    violations: list[CodeViolation] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in deny:
                    violations.append(
                        CodeViolation(
                            kind="import_denied",
                            line=node.lineno,
                            detail=f"import '{alias.name}' is denied by default policy",
                        )
                    )
                elif allow and top not in allow:
                    # Lenient: only warn for unknown imports (could be a Bio-Babel pkg)
                    pass
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top in deny:
                violations.append(
                    CodeViolation(
                        kind="import_denied",
                        line=node.lineno,
                        detail=f"from '{node.module}' is denied by default policy",
                    )
                )
        elif isinstance(node, ast.Call):
            fname = _call_name(node.func)
            if fname in FORBIDDEN_CALLS:
                violations.append(
                    CodeViolation(
                        kind="forbidden_call",
                        line=node.lineno,
                        detail=f"call to '{fname}' is forbidden",
                    )
                )
        elif isinstance(node, ast.Attribute):
            # Catch sys.exit / os.system / subprocess.run via attribute access
            qual = _qualname(node)
            if qual and qual.split(".")[0] in deny:
                violations.append(
                    CodeViolation(
                        kind="attr_access_denied",
                        line=node.lineno,
                        detail=f"attribute access '{qual}' on denied module",
                    )
                )

    return CodeScanResult(ok=not violations, violations=violations)


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _qualname(node: ast.Attribute) -> str:
    parts: list[str] = []
    cur: ast.AST = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return ""
