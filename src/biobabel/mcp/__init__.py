"""MCP server — 20 tools across 6 groups."""

from biobabel.mcp.envelope import error, success
from biobabel.mcp.server import BiobabelMCPServer, build_server

__all__ = ["BiobabelMCPServer", "build_server", "error", "success"]
