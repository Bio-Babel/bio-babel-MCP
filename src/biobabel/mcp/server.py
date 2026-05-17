"""biobabel MCP server — wires the 22 tools to a dispatch table.

We keep the dispatch decoupled from any specific MCP SDK so the same handlers
can be smoke-tested in pytest and shipped through stdio / http transports.
The Anthropic `mcp` SDK is wired in the `transports/stdio.py` adapter.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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

ToolHandler = Callable[..., dict[str, Any]]


@dataclass
class ToolSpec:
    name: str
    group: str
    handler: ToolHandler
    description: str


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
                  "Task → WorkflowContract or ad-hoc DAG")
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

        # Group 5 — Runtime (8)
        self._add("biobabel.create_session", "runtime",
                  lambda **kw: runtime.create_session(sess, **kw),
                  "Create a new sandboxed session")
        self._add("biobabel.list_handles", "runtime",
                  lambda **kw: runtime.list_handles(sess, **kw),
                  "List handles in a session")
        self._add("biobabel.load_adata", "runtime",
                  lambda **kw: runtime.load_adata(sess, **kw),
                  "Load an h5ad into an AdataHandle")
        self._add("biobabel.load_dataframe", "runtime",
                  lambda **kw: runtime.load_dataframe(sess, **kw),
                  "Load a CSV/TSV/Parquet into a DfHandle")
        self._add("biobabel.run_code", "runtime",
                  lambda **kw: runtime.run_code(reg, sess, **kw),
                  "Execute Python code in the sandbox")
        self._add("biobabel.run_recipe", "runtime",
                  lambda **kw: runtime.run_recipe(reg, sess, **kw),
                  "Run a registered recipe by id")
        self._add("biobabel.inspect_object", "runtime",
                  lambda **kw: runtime.inspect_object(sess, **kw),
                  "Inspect a slot of an adata handle")
        self._add("biobabel.get_artifact", "runtime",
                  lambda **kw: runtime.get_artifact(sess, **kw),
                  "Fetch artifact content + provenance")

        # Group 6 — Meta (3)
        self._add("biobabel.list_tools", "meta",
                  lambda **kw: meta.list_tools(list(self._tools)),
                  "List all MCP tools")
        self._add("biobabel.health", "meta",
                  lambda **kw: meta.health(reg, sess),
                  "Registry + session health snapshot")
        self._add("biobabel.list_traces", "meta",
                  lambda **kw: meta.list_traces(sess, **kw),
                  "Recent tool-call traces in a session")

    def _add(self, name: str, group: str, handler: ToolHandler, description: str) -> None:
        self._tools[name] = ToolSpec(name=name, group=group, handler=handler, description=description)

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def tool_names(self) -> list[str]:
        return sorted(self._tools)

    def tool(self, name: str) -> ToolSpec:
        return self._tools[name]

    def call(self, name: str, **kwargs: Any) -> dict[str, Any]:
        if name not in self._tools:
            from biobabel.mcp.envelope import error
            return error(name, error_code="unknown_tool", message=f"no tool '{name}'")
        return self._tools[name].handler(**kwargs)


def build_server() -> BiobabelMCPServer:
    return BiobabelMCPServer()
