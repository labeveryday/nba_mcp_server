"""NBA MCP Server - Access NBA statistics via Model Context Protocol."""

import asyncio

from nba_mcp_server.server import main as async_main

__version__ = "0.1.5"

def main():
    """Entry point that runs the async main function."""
    asyncio.run(async_main())

__all__ = ["main", "__version__"]
