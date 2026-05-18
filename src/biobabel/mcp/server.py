"""biobabel MCP server — wires the 20 tools to a dispatch table.

We keep the dispatch decoupled from any specific MCP SDK so the same handlers
can be smoke-tested in pytest and shipped through stdio / http transports.
The Anthropic `mcp` SDK is wired in the `transports/stdio.py` adapter.

Surface trim history:
- 27 → 22: ``biobabel.recommend`` removed; the LLM ranks packages itself
  from ``list_packages`` triggers/tags/capabilities.
- 22 → 20: ``biobabel.create_session`` and ``biobabel.list_handles``
  removed from the public surface as part of the P2-2 + P2-3 bundle.
  Sessions are now server-side plumbing (lazy default) and current
  handles are echoed in every runtime tool's ``outputs.active_handles``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from biobabel._registry.builder import Registry, build_registry
from biobabel._runtime.session import SessionStore
from biobabel.mcp.tools import (
    concept,
    discovery,
    meta,
    planning,
    runtime,
    validation,
)
from biobabel.mcp.tools.runtime import ProgressEmitter, _noop_progress
from biobabel.mcp.tracing import record_runtime_trace

ToolHandler = Callable[..., dict[str, Any]]


@dataclass
class ToolSpec:
    name: str
    group: str
    handler: ToolHandler
    description: str
    # True for handlers that accept an injected ``progress: ProgressEmitter``
    # as their first positional argument after the bound dependencies.
    # Streaming tools (``run_code`` / ``run_recipe``) forward subprocess
    # output through it as MCP ``notifications/progress``; non-streaming
    # runtime handlers receive a noop emitter so the signature stays
    # uniform across the group.
    streams: bool = False
    # True for runtime-group handlers that accept ``progress`` as the third
    # positional. Distinct from ``streams``: every runtime tool wants
    # ``progress`` injected even though only two actually emit through it.
    accepts_progress: bool = False


class BiobabelMCPServer:
    def __init__(
        self,
        registry: Registry | None = None,
        sessions: SessionStore | None = None,
    ) -> None:
        self.registry = registry or build_registry()
        self.sessions = sessions or SessionStore()
        self._tools: dict[str, ToolSpec] = {}
        self._wire()

    def _wire(self) -> None:
        reg = self.registry
        sess = self.sessions

        # Group 1 — Discovery (5)
        self._add("biobabel.list_packages", "discovery",
                  lambda **kw: discovery.list_packages(reg, **kw),
                  "List registered Bio-Babel packages with class/tier/maturity filters")
        self._add("biobabel.search", "discovery",
                  lambda **kw: discovery.search(reg, **kw),
                  "Cross-package symbol/recipe/idiom/concept search")
        self._add("biobabel.describe_package", "discovery",
                  lambda **kw: discovery.describe_package(reg, **kw),
                  "Full PackageManifest, pruned to relevant fields for the class")
        self._add("biobabel.describe_symbol", "discovery",
                  lambda **kw: discovery.describe_symbol(reg, **kw),
                  "FunctionContract details incl. extended_by reverse index")
        self._add("biobabel.describe_workflow", "discovery",
                  lambda **kw: discovery.describe_workflow(reg, **kw),
                  "WorkflowContract details (Class A)")

        # Group 2 — Planning (2)
        # NOTE: package recommendation is deliberately not a tool. LLMs rank
        # packages from biobabel.list_packages' triggers/tags/capabilities.
        self._add("biobabel.plan_workflow", "planning",
                  lambda **kw: planning.plan_workflow(reg, **kw),
                  "Task → declared WorkflowContract or source='none'")
        self._add("biobabel.check_prerequisites", "planning",
                  lambda **kw: planning.check_prerequisites(reg, sess, **kw),
                  "Validate a step against the current adata snapshot")

        # Group 3 — Concept Layer (3)
        self._add("biobabel.describe_concept", "concept",
                  lambda **kw: concept.describe_concept(reg, **kw),
                  "ConceptSpec with invariants and mental model")
        self._add("biobabel.list_idioms", "concept",
                  lambda **kw: concept.list_idioms(reg, **kw),
                  "Idioms filtered by package / applicable_to / task")
        self._add("biobabel.describe_idiom", "concept",
                  lambda **kw: concept.describe_idiom(reg, **kw),
                  "IdiomSpec with code template")

        # Group 4 — Validation (1)
        self._add("biobabel.check_code", "validation",
                  lambda **kw: validation.check_code(reg, **kw),
                  "Semantic lint: security scan + anti-pattern match")

        # Group 5 — Runtime (6, was 8). All accept ``progress`` injected
        # by ``call()``. The two streaming members (run_code, run_recipe)
        # forward subprocess stdout/stderr chunks through it.
        self._add("biobabel.load_adata", "runtime",
                  lambda progress, **kw: runtime.load_adata(sess, progress, **kw),
                  "Load an h5ad into an AdataHandle",
                  accepts_progress=True)
        self._add("biobabel.load_dataframe", "runtime",
                  lambda progress, **kw: runtime.load_dataframe(sess, progress, **kw),
                  "Load a CSV/TSV/Parquet into a DfHandle",
                  accepts_progress=True)
        self._add("biobabel.run_code", "runtime",
                  lambda progress, **kw: runtime.run_code(reg, sess, progress, **kw),
                  "Execute Python code in the sandbox (streams stdout/stderr)",
                  accepts_progress=True, streams=True)
        self._add("biobabel.run_recipe", "runtime",
                  lambda progress, **kw: runtime.run_recipe(reg, sess, progress, **kw),
                  "Run a registered recipe by id (streams stdout/stderr)",
                  accepts_progress=True, streams=True)
        self._add("biobabel.inspect_object", "runtime",
                  lambda progress, **kw: runtime.inspect_object(sess, progress, **kw),
                  "Inspect a slot of an adata handle",
                  accepts_progress=True)
        self._add("biobabel.get_artifact", "runtime",
                  lambda progress, **kw: runtime.get_artifact(sess, progress, **kw),
                  "Fetch artifact content + provenance",
                  accepts_progress=True)

        # Group 6 — Meta (3)
        self._add("biobabel.list_tools", "meta",
                  lambda **kw: meta.list_tools(list(self._tools)),
                  "List all MCP tools")
        self._add("biobabel.health", "meta",
                  lambda **kw: meta.health(reg, sess),
                  "Registry + session health snapshot incl. per-session handles")
        self._add("biobabel.list_traces", "meta",
                  lambda **kw: meta.list_traces(sess, **kw),
                  "Recent tool-call traces in a session")

    def _add(
        self,
        name: str,
        group: str,
        handler: ToolHandler,
        description: str,
        *,
        accepts_progress: bool = False,
        streams: bool = False,
    ) -> None:
        self._tools[name] = ToolSpec(
            name=name,
            group=group,
            handler=handler,
            description=description,
            accepts_progress=accepts_progress,
            streams=streams,
        )

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def tool_names(self) -> list[str]:
        return sorted(self._tools)

    def tool(self, name: str) -> ToolSpec:
        return self._tools[name]

    def call(
        self,
        name: str,
        *,
        progress: ProgressEmitter | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if name not in self._tools:
            from biobabel.mcp.envelope import error
            return error(name, error_code="unknown_tool", message=f"no tool '{name}'")
        spec = self._tools[name]
        if spec.group == "runtime":
            return self._call_runtime_tool(spec, progress=progress, kwargs=kwargs)
        if spec.accepts_progress:
            return spec.handler(progress or _noop_progress, **kwargs)
        return spec.handler(**kwargs)

    def _call_runtime_tool(
        self,
        spec: ToolSpec,
        *,
        progress: ProgressEmitter | None,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc)
        start = time.perf_counter()
        try:
            env = spec.handler(progress or _noop_progress, **kwargs)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            record_runtime_trace(
                self.sessions,
                spec.name,
                kwargs=kwargs,
                envelope=None,
                started_at=started_at,
                duration_ms=duration_ms,
                exception=exc,
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        record_runtime_trace(
            self.sessions,
            spec.name,
            kwargs=kwargs,
            envelope=env,
            started_at=started_at,
            duration_ms=duration_ms,
        )
        return env


def build_server() -> BiobabelMCPServer:
    return BiobabelMCPServer()
