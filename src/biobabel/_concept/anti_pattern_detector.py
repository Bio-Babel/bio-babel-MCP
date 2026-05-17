"""AST-based anti-pattern detection.

Producer-side detectors register a callable under the ``biobabel.detectors``
entry-point group; their detector_id is then referenced from each
AntiPatternSpec.detection.detector_id field in the producer's YAML. biobabel
core hosts no built-in detectors — that's deliberate, the producer owns the
domain knowledge.

Plain regex detection (``detection.regex``) needs no callable registration
and is matched here directly.

Error handling:

- Producer references a ``detector_id`` for which no detector is registered:
  raise loudly. Producer-config bug; static failure is preferable to silent
  skipping.
- Registered detector raises during execution: capture and convert into an
  error-severity ``AntiPatternMatch`` so one buggy detector cannot break
  the whole lint, while the failure remains visible to the LLM and to logs.
"""

from __future__ import annotations

import ast
import re
import traceback
from dataclasses import dataclass, field

from biobabel._registry.builder import Registry
from biobabel.manifest_api import AntiPatternSpec


@dataclass
class AntiPatternMatch:
    anti_pattern_id: str
    severity: str
    line: int
    message: str
    suggestion_idiom: str | None = None
    code_example_right: str = ""
    detail: dict[str, object] = field(default_factory=dict)


def detect_anti_patterns(
    code: str,
    *,
    registry: Registry,
    package: str | None = None,
) -> list[AntiPatternMatch]:
    """Run every registered anti-pattern's detection over *code*."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [
            AntiPatternMatch(
                anti_pattern_id="<syntax_error>",
                severity="error",
                line=exc.lineno or 0,
                message=f"Cannot parse: {exc}",
            )
        ]

    matches: list[AntiPatternMatch] = []
    for pkg, spec in registry.all_anti_patterns():
        if package and pkg != package:
            continue
        matches.extend(_run_one(tree, code, spec, registry))
    return matches


def _run_one(
    tree: ast.AST,
    code: str,
    spec: AntiPatternSpec,
    registry: Registry,
) -> list[AntiPatternMatch]:
    matches: list[AntiPatternMatch] = []

    if spec.detection.detector_id:
        discovered = registry.detector(spec.detection.detector_id)
        if discovered is None:
            available = sorted(registry.detectors)
            raise RuntimeError(
                f"anti-pattern {spec.id!r} references detector "
                f"{spec.detection.detector_id!r} but no detector was "
                f"registered under that name. "
                f"Producer should declare it in pyproject.toml under "
                f"[project.entry-points.\"biobabel.detectors\"]. "
                f"Currently registered detector_ids: {available}"
            )
        # The detector itself is producer code; isolate its failures so one
        # broken detector cannot break the whole anti-pattern lint, but
        # surface them as error-severity matches rather than swallowing.
        try:
            hits = discovered.fn(tree, dict(spec.detection.args))
        except Exception as exc:  # noqa: BLE001 — error surfaced into output
            matches.append(
                AntiPatternMatch(
                    anti_pattern_id=spec.id,
                    severity="error",
                    line=0,
                    message=(
                        f"detector {spec.detection.detector_id!r} raised "
                        f"{type(exc).__name__}: {exc}"
                    ),
                    detail={
                        "detector_id": spec.detection.detector_id,
                        "distribution": discovered.distribution,
                        "distribution_version": discovered.distribution_version,
                        "traceback": traceback.format_exc(),
                    },
                )
            )
        else:
            for hit in hits:
                matches.append(
                    AntiPatternMatch(
                        anti_pattern_id=spec.id,
                        severity="warning",
                        line=hit.line,
                        message=spec.why_bad or spec.name,
                        suggestion_idiom=spec.correct_pattern,
                        code_example_right=spec.code_example_right,
                        detail=hit.detail,
                    )
                )

    if spec.detection.regex:
        for m in re.finditer(spec.detection.regex, code):
            line = code.count("\n", 0, m.start()) + 1
            matches.append(
                AntiPatternMatch(
                    anti_pattern_id=spec.id,
                    severity="warning",
                    line=line,
                    message=spec.why_bad or spec.name,
                    suggestion_idiom=spec.correct_pattern,
                    code_example_right=spec.code_example_right,
                    detail={"match": m.group(0)},
                )
            )

    return matches
