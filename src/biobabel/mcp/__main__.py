"""`python -m biobabel.mcp` and `biobabel-mcp` console script entry point."""

from __future__ import annotations

import sys

from biobabel.mcp.server import build_server
from biobabel.mcp.transports.stdio import StdioTransport


def main(argv: list[str] | None = None) -> int:
    _ = argv  # reserved for future flags (--http, --port, ...)
    server = build_server()
    StdioTransport(server).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
