"""Task → ranked package recommendation.

Implementation: keyword + tf-idf-style scoring against task_tags / triggers /
domain_tags / capabilities. Penalize `not_when`. Boost stable > beta > alpha.
No ML dependency.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from biobabel._registry.builder import Registry

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


@dataclass
class Recommendation:
    package: str
    confidence: float
    rationale: str
    alternatives: list[str]


def recommend(registry: Registry, task: str, *, k: int = 3) -> list[Recommendation]:
    task_toks = _tokens(task)
    if not task_toks:
        return []

    # Pre-compute IDF over the corpus of package documents.
    docs: dict[str, list[str]] = {}
    for d in registry.packages.values():
        m = d.manifest
        parts: list[str] = [
            m.display_name,
            m.import_name,
            " ".join(m.task_tags),
            " ".join(m.domain_tags),
            " ".join(m.capabilities),
            " ".join(t.intent for t in m.triggers),
        ]
        docs[d.import_name] = _tokens(" ".join(parts))

    if not docs:
        return []

    df: Counter[str] = Counter()
    for toks in docs.values():
        for tok in set(toks):
            df[tok] += 1
    n_docs = len(docs)
    idf = {tok: math.log(1 + n_docs / (1 + count)) for tok, count in df.items()}

    scored: list[tuple[str, float, str]] = []
    for import_name, toks in docs.items():
        manifest = registry.manifest(import_name)
        if manifest is None:
            continue

        tf = Counter(toks)
        score = 0.0
        matched: list[str] = []
        for q in task_toks:
            w = idf.get(q, 0.0) * tf.get(q, 0)
            if w > 0:
                score += w
                matched.append(q)

        # Trigger boost
        for trigger in manifest.triggers:
            if all(t in task.lower() for t in _tokens(trigger.intent)):
                score += 1.5 * trigger.confidence
                matched.append(f"trigger:{trigger.intent}")

        # not_when penalty
        for nw in manifest.not_when:
            if any(t in task.lower() for t in _tokens(nw)):
                score *= 0.4

        # maturity preference
        score *= {"stable": 1.0, "beta": 0.85, "alpha": 0.7}.get(manifest.maturity, 0.7)

        if score > 0:
            rationale = (
                f"matched: {', '.join(matched[:5])}; "
                f"class={manifest.contract_class}; maturity={manifest.maturity}"
            )
            scored.append((import_name, score, rationale))

    scored.sort(key=lambda t: t[1], reverse=True)
    top = scored[:k]
    if not top:
        return []
    max_score = top[0][1] or 1.0

    others = [name for name, _, _ in scored[k : k + 3]]
    return [
        Recommendation(
            package=name,
            confidence=round(min(score / max_score, 1.0), 3),
            rationale=rationale,
            alternatives=others,
        )
        for name, score, rationale in top
    ]


def search_text(registry: Registry, query: str, *, kinds: Iterable[str] = ("function", "concept", "idiom", "recipe")) -> list[dict[str, str]]:
    """Cross-package symbol / concept / idiom / recipe search."""
    kinds_set = set(kinds)
    q_toks = set(_tokens(query))
    hits: list[tuple[float, dict[str, str]]] = []

    for d in registry.packages.values():
        m = d.manifest
        if "function" in kinds_set:
            for fn in m.functions:
                doc = f"{fn.id} {fn.description} {' '.join(fn.intent)}"
                s = _overlap(doc, q_toks)
                if s > 0:
                    hits.append(
                        (s, {"kind": "function", "id": fn.id, "package": d.import_name, "summary": fn.description[:120]})
                    )
        if "concept" in kinds_set:
            for c in m.concepts:
                doc = f"{c.id} {c.name} {c.description}"
                s = _overlap(doc, q_toks)
                if s > 0:
                    hits.append(
                        (s, {"kind": "concept", "id": c.id, "package": d.import_name, "summary": c.description[:120]})
                    )
        if "idiom" in kinds_set:
            for i in m.idioms:
                doc = f"{i.id} {i.name} {i.description} {i.typical_use_case}"
                s = _overlap(doc, q_toks)
                if s > 0:
                    hits.append(
                        (s, {"kind": "idiom", "id": i.id, "package": d.import_name, "summary": i.description[:120]})
                    )
        if "recipe" in kinds_set:
            for r in m.recipes:
                doc = f"{r.id} {r.description} {' '.join(r.task_tags)}"
                s = _overlap(doc, q_toks)
                if s > 0:
                    hits.append(
                        (s, {"kind": "recipe", "id": r.id, "package": d.import_name, "summary": r.description[:120]})
                    )

    hits.sort(key=lambda t: t[0], reverse=True)
    return [h for _, h in hits[:30]]


def _overlap(doc: str, q_toks: set[str]) -> float:
    d_toks = set(_tokens(doc))
    return float(len(d_toks & q_toks))
