"""Public API for biobabel AST anti-pattern detectors.

This is the **second** stable public surface of biobabel (the first being
:mod:`biobabel.manifest_api`). Upstream Bio-Babel packages register
detector callables via the ``biobabel.detectors`` entry-point group; each
callable receives a parsed AST and a dict of arguments from the
corresponding :class:`AntiPatternSpec.detection.args` field, and returns
a list of :class:`DetectorMatch` instances.

Producers are self-describing: adding a new AST detector kind is done by
shipping a callable + an entry-point line in the producer's
``pyproject.toml``, with no change required in biobabel core.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DetectorMatch:
    """One concrete hit produced by a detector callable.

    The line number is the source line in the user code where the pattern
    was found. The detail dict is free-form structured data that the
    detector wants to surface to the LLM (e.g. ``{"target_call": "rect_grob"}``)
    — it is passed through verbatim into the resulting AntiPatternMatch.
    """

    line: int
    detail: dict[str, Any] = field(default_factory=dict)


DetectorFn = Callable[[ast.AST, dict[str, Any]], list[DetectorMatch]]
"""Signature every registered detector must satisfy.

Detectors are pure functions of ``(tree, args)``. They must not mutate the
tree, must not perform I/O, and must not raise on well-formed input; if
they do raise, biobabel surfaces the exception as an error-severity
match rather than swallowing it.
"""
