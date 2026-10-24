"""The MCP server. Every tool is read-only and says so (dev/DESIGN.md, "Safety")."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import __version__

# Every tool of this server carries these annotations; a test holds it.
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False)

INSTRUCTIONS = (
    "repo-reader-mcp reads code in git repositories and never changes them. Pre-alpha: only `about` exists so far."
)


def build_server() -> MCPServer:
    """The server with its tools — built fresh, so tests and transports each get their own."""
    server = MCPServer(name="repo-reader-mcp", version=__version__, instructions=INSTRUCTIONS)

    @server.tool(annotations=READ_ONLY)
    def about() -> dict:
        """What this server is and what it will offer. Call it to check the connection."""
        return {
            "name": "repo-reader-mcp",
            "version": __version__,
            "status": "pre-alpha: repository tools are being built",
            "read_only": True,
        }

    return server


def main() -> None:
    """The console entry point: the server over stdio."""
    build_server().run("stdio")


if __name__ == "__main__":
    main()
