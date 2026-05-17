"""Cross-package text search over functions / concepts / idioms / recipes.

Filters by query-token presence in the document; does **not** rank. Ranking
— when needed — is the LLM's job. biobabel surfaces signals; the consumer
side decides what's relevant.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from biobabel._registry.builder import Registry

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")

_VALID_KINDS: frozenset[str] = frozenset({"function", "concept", "idiom", "recipe"})
_DEFAULT_KINDS: tuple[str, ...] = ("function", "concept", "idiom", "recipe")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text)}


def search_text(
    registry: Registry,
    query: str,
    *,
    kinds: Iterable[str] = _DEFAULT_KINDS,
) -> list[dict[str, str]]:
    """Return every entry of the requested kinds whose tokens overlap *query*.

    No scoring, no truncation. Sorted by ``(package, kind, id)`` for
    determinism, so the consumer always sees the same payload for the same
    query + registry state.
    """
    kinds_set = set(kinds)
    unknown = kinds_set - _VALID_KINDS
    if unknown:
        raise ValueError(
            f"unknown search kinds: {sorted(unknown)}; valid: {sorted(_VALID_KINDS)}"
        )

    q_toks = _tokens(query)
    if not q_toks:
        return []

    hits: list[dict[str, str]] = []
    for d in registry.packages.values():
        m = d.manifest
        if "function" in kinds_set:
            for fn in m.functions:
                doc = f"{fn.id} {fn.description} {' '.join(fn.intent)}"
                if _tokens(doc) & q_toks:
                    hits.append(
                        {
                            "kind": "function",
                            "id": fn.id,
                            "package": d.import_name,
                            "summary": fn.description[:120],
                        }
                    )
        if "concept" in kinds_set:
            for c in m.concepts:
                doc = f"{c.id} {c.name} {c.description}"
                if _tokens(doc) & q_toks:
                    hits.append(
                        {
                            "kind": "concept",
                            "id": c.id,
                            "package": d.import_name,
                            "summary": c.description[:120],
                        }
                    )
        if "idiom" in kinds_set:
            for i in m.idioms:
                doc = f"{i.id} {i.name} {i.description} {i.typical_use_case}"
                if _tokens(doc) & q_toks:
                    hits.append(
                        {
                            "kind": "idiom",
                            "id": i.id,
                            "package": d.import_name,
                            "summary": i.description[:120],
                        }
                    )
        if "recipe" in kinds_set:
            for r in m.recipes:
                doc = f"{r.id} {r.description} {' '.join(r.task_tags)}"
                if _tokens(doc) & q_toks:
                    hits.append(
                        {
                            "kind": "recipe",
                            "id": r.id,
                            "package": d.import_name,
                            "summary": r.description[:120],
                        }
                    )

    hits.sort(key=lambda h: (h["package"], h["kind"], h["id"]))
    return hits
