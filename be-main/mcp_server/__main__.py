"""Research.it over MCP's stdio transport, for desktop clients.

    python -m mcp_server

Reads the same DATABASE_URL and LLM provider settings as the API. stdout
carries the protocol, so logs go to stderr.
"""

import sys

from db.bootstrap import ensure_schema
from logging_config import configure_logging
from mcp_server.server import build_server


def main() -> None:
    configure_logging(stream=sys.stderr)
    ensure_schema()
    build_server().run("stdio")


if __name__ == "__main__":
    main()
