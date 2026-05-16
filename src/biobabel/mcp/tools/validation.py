"""Group 5 — Validation (1 tool: check_code)."""

from __future__ import annotations

from typing import Any

from biobabel._concept.anti_pattern_detector import detect_anti_patterns
from biobabel._registry.builder import Registry
from biobabel._runtime.policy import scan_code
from biobabel.mcp.envelope import success


def check_code(
    registry: Registry,
    *,
    code: str,
    package: str | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []

    scan = scan_code(code, extra_allow=list(registry.packages.keys()))
    for v in scan.violations:
        issues.append(
            {
                "kind": "security",
                "severity": "error",
                "line": v.line,
                "message": v.detail,
                "fix_suggestion": "remove disallowed import or call",
            }
        )

    for m in detect_anti_patterns(code, registry=registry, package=package):
        issues.append(
            {
                "kind": "anti_pattern",
                "severity": m.severity,
                "line": m.line,
                "message": m.message,
                "anti_pattern_id": m.anti_pattern_id,
                "fix_suggestion": m.suggestion_idiom or "",
                "code_example_right": m.code_example_right,
            }
        )

    return success(
        "biobabel.check_code",
        summary=f"{len(issues)} issue(s)",
        outputs={"issues": issues, "code_safe": scan.ok},
    )
