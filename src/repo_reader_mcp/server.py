"""The MCP server. Every tool is read-only and says so (dev/DESIGN.md, "Safety")."""

from __future__ import annotations

import argparse
import os
import sys

from mcp.server.mcpserver import MCPServer

from . import __version__
from .config import Config, ConfigError, load_config
from .tools import READ_ONLY, register

CONFIG_VARIABLE = "REPO_READER_MCP_CONFIG"

INSTRUCTIONS = (
    "repo-reader-mcp reads code in git repositories and never changes them. Start with `list_repos`. Every tool "
    "takes `repo` (a name from list_repos); the reading tools take `ref` — any branch, tag or commit id — and read the "
    "default branch without it. Paths are written from the repository's root, like `src/app.py`. Every answer names "
    "the commit it was read at; long answers are cut and say how to continue."
)


def build_server(config: Config | None = None) -> MCPServer:
    """The server with its tools — built fresh, so tests and transports each get their own."""
    config = config or Config()
    server = MCPServer(name="repo-reader-mcp", version=__version__, instructions=INSTRUCTIONS)

    @server.tool(annotations=READ_ONLY)
    def about() -> dict:
        """What this server is and its version. Call it to check the connection."""
        return {
            "name": "repo-reader-mcp",
            "version": __version__,
            "status": "pre-alpha: local repositories",
            "read_only": True,
            "repositories": len(config.repositories),
        }

    register(server, config)
    return server


def main(argv: list[str] | None = None) -> None:
    """The console entry point: check the configuration, then serve over stdio."""
    parser = argparse.ArgumentParser(prog="repo-reader-mcp", description=__doc__)
    parser.add_argument(
        "--config", default=os.environ.get(CONFIG_VARIABLE), help=f"the configuration file (or set {CONFIG_VARIABLE})"
    )
    parser.add_argument("--check", action="store_true", help="check the configuration, list what it serves, and exit")
    args = parser.parse_args(argv)
    if not args.config:
        parser.exit(2, f"repo-reader-mcp: no configuration — pass --config FILE or set {CONFIG_VARIABLE}\n")
    try:
        config = load_config(args.config)
    except ConfigError as error:
        parser.exit(2, f"repo-reader-mcp: {error}\n")
    if args.check:
        count = len(config.repositories)
        print(f"The configuration {args.config} is good — it serves {count} repositor{'y' if count == 1 else 'ies'}:")
        for repo in config.repositories:
            print(f"  {repo.name}  {repo.path}")
        return
    build_server(config).run("stdio")


if __name__ == "__main__":
    main(sys.argv[1:])
