"""AST-based anti-pattern detection driven by AntiPatternSpec.detection.

`detection.ast_pattern` is a small DSL:

    "for_loop_calls:rect_grob,text_grob,line_to_grob"
        → any `for` body whose direct call expressions hit any of those names
    "unbalanced:push_viewport,pop_viewport"
        → count(push_viewport) != count(pop_viewport) at module level
    "kwarg_value:Unit:units=npc:and_used_in:obs|data"
        → calls Unit(..., units='npc') in a context referring to data coords

The DSL is intentionally small — we only support patterns that real
anti_patterns/*.yaml actually need. New kinds are added in `_DETECTORS`.

Plain regex (`detection.regex`) is matched as a fallback / supplement.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Callable

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
    """Run all anti-pattern detectors over *code* and return matches."""
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
        matches.extend(_run_one(tree, code, spec))
    return matches


def _run_one(tree: ast.AST, code: str, spec: AntiPatternSpec) -> list[AntiPatternMatch]:
    matches: list[AntiPatternMatch] = []

    if spec.detection.ast_pattern:
        kind, _, arg = spec.detection.ast_pattern.partition(":")
        detector = _DETECTORS.get(kind)
        if detector:
            for line, detail in detector(tree, arg):
                matches.append(
                    AntiPatternMatch(
                        anti_pattern_id=spec.id,
                        severity="warning",
                        line=line,
                        message=spec.why_bad or spec.name,
                        suggestion_idiom=spec.correct_pattern,
                        code_example_right=spec.code_example_right,
                        detail=detail,
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


# --- detectors ------------------------------------------------------------

Detector = Callable[[ast.AST, str], list[tuple[int, dict[str, object]]]]


def _det_for_loop_calls(tree: ast.AST, arg: str) -> list[tuple[int, dict[str, object]]]:
    """Match: any `for` body that calls one of *targets*."""
    targets = {t.strip() for t in arg.split(",") if t.strip()}
    hits: list[tuple[int, dict[str, object]]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.AsyncFor)):
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    name = _call_name(child.func)
                    if name in targets:
                        hits.append((node.lineno, {"target_call": name}))
                        break
    return hits


def _det_unbalanced(tree: ast.AST, arg: str) -> list[tuple[int, dict[str, object]]]:
    """Match: count(push_fn) != count(pop_fn) at module/function scope."""
    parts = [p.strip() for p in arg.split(",")]
    if len(parts) != 2:
        return []
    push_fn, pop_fn = parts

    push_count = 0
    pop_count = 0
    first_push_line = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name == push_fn:
                push_count += 1
                if first_push_line == 0:
                    first_push_line = node.lineno
            elif name == pop_fn:
                pop_count += 1

    if push_count != pop_count:
        return [
            (
                first_push_line or 1,
                {"push_count": push_count, "pop_count": pop_count, "diff": push_count - pop_count},
            )
        ]
    return []


def _det_unit_kw(tree: ast.AST, arg: str) -> list[tuple[int, dict[str, object]]]:
    """Match: `Unit(value, 'npc')` used for actual data coordinates.

    Heuristic: any positional or keyword `units='npc'` (or 'snpc') argument
    to a call named `Unit` whose value comes from a Name/Subscript referencing
    a typical data variable (df/data/values/x/y). This is intentionally
    conservative — the goal is to flag the obvious anti-pattern, not catch all.
    """
    bad_units = {u.strip() for u in arg.split(",") if u.strip()} or {"npc", "snpc"}
    data_hints = {"df", "data", "values", "x", "y", "obs"}
    hits: list[tuple[int, dict[str, object]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node.func) == "Unit":
            units_value = _extract_unit_kw(node)
            if units_value not in bad_units:
                continue
            first_arg = node.args[0] if node.args else None
            if first_arg is None:
                continue
            referenced = _names_in(first_arg)
            if referenced & data_hints:
                hits.append((node.lineno, {"units": units_value, "referenced": sorted(referenced)}))
    return hits


_DETECTORS: dict[str, Detector] = {
    "for_loop_calls": _det_for_loop_calls,
    "unbalanced": _det_unbalanced,
    "unit_kw": _det_unit_kw,
}


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _extract_unit_kw(call: ast.Call) -> str:
    for kw in call.keywords:
        if kw.arg == "units" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    if len(call.args) >= 2:
        a = call.args[1]
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            return a.value
    return ""


def _names_in(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
            out.add(n.value.id)
    return out
