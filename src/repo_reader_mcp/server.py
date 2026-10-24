"""The MCP server. Every tool is read-only and says so (dev/DESIGN.md, "Safety")."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from mcp.server.mcpserver import MCPServer

from . import __version__
from .config import Config, ConfigError, load_config
from .guidance import gather, out_of_reach
from .mirror import Mirror, SyncError, keep_fresh, sync_all
from .repository import ReadError, Repository
from .tools import READ_ONLY, register

CONFIG_VARIABLE = "REPO_READER_MCP_CONFIG"

INSTRUCTIONS = (
    "repo-reader-mcp reads code in git repositories and never changes them. Start with `list_repos`. Every tool "
    "takes `repo` (a name from list_repos); the reading tools take `ref` — any branch, tag or commit id — and read the "
    "default branch without it. Paths are written from the repository's root, like `src/app.py`. Every answer names "
    "the commit it was read at; long answers are cut and say how to continue. A repository may carry guidance written "
    "for agents by its owners and by the people who run this server — rules to follow while working with it. An "
    "answer about such a repository says so: read it with `read_guidance` once in a conversation, and follow it; an "
    "answer about a path a short rule covers carries that rule."
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
            "status": "pre-alpha: local and mirrored remote repositories",
            "read_only": True,
            "repositories": len(config.repositories),
        }

    register(server, config)
    return server


def check(source: str, config: Config) -> None:
    """What `--check` prints: the repositories served — a remote one's host asked whether it answers — the guidance
    each carries, and guidance agents won't get."""
    count = len(config.repositories)
    print(f"The configuration {source} is good — it serves {count} repositor{'y' if count == 1 else 'ies'}:")
    every = {repo.name: Repository(repo) for repo in config.repositories}
    for repo in config.repositories:
        mirror = every[repo.name].mirror
        where = mirror.remote.url if mirror else repo.path
        print(f"  {repo.name}  {where}" + ("" if repo.listed else "  (not listed: a source of guidance only)"))
        if mirror is not None:
            state = "made" if mirror.ready else "not made yet: the first sync makes it"
            print(f"    mirror: {mirror.git_dir} ({state})")
            try:
                print(f"    host: {mirror.reach()}")
            except SyncError as error:
                print(f"    host: can't be reached: {error}")
            if not mirror.ready:
                continue
        try:
            docs = gather(repo, config.guidance, every).docs
        except ReadError as error:
            print(f"    guidance can't be read: {error}")
            continue
        if docs:
            print(f"    guidance: {', '.join(doc.name for doc in docs)}")
        for path in out_of_reach(every[repo.name]):
            print(
                f"    warning: {path} is guidance for agents, but outside its include / exclude — agents won't get it"
            )


def sync_once(config: Config) -> bool:
    """What `--sync` prints: every mirror brought up to date once, and how; whether all of them worked."""
    mirrors = [Mirror(repo) for repo in config.repositories if repo.remote]
    if not mirrors:
        print("No remote repositories are configured: nothing to sync.")
        return True
    results = sync_all(mirrors)
    for mirror, outcome, worked in results:
        print(f"  {mirror.name}: {outcome if worked else 'failed: ' + outcome}")
    return all(worked for _, _, worked in results)


def main(argv: list[str] | None = None) -> None:
    """The console entry point: check the configuration, then serve over stdio — syncing mirrors in the background."""
    parser = argparse.ArgumentParser(prog="repo-reader-mcp", description=__doc__)
    parser.add_argument(
        "--config", default=os.environ.get(CONFIG_VARIABLE), help=f"the configuration file (or set {CONFIG_VARIABLE})"
    )
    parser.add_argument("--check", action="store_true", help="check the configuration, list what it serves, and exit")
    parser.add_argument("--sync", action="store_true", help="bring every mirror up to date once, and exit")
    args = parser.parse_args(argv)
    if not args.config:
        parser.exit(2, f"repo-reader-mcp: no configuration — pass --config FILE or set {CONFIG_VARIABLE}\n")
    try:
        config = load_config(args.config)
    except ConfigError as error:
        parser.exit(2, f"repo-reader-mcp: {error}\n")
    if args.check:
        check(args.config, config)
        return
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="repo-reader-mcp: %(message)s")
    if args.sync:
        if not sync_once(config):
            parser.exit(1)
        return
    mirrors = [Mirror(repo) for repo in config.repositories if repo.remote]
    if mirrors:
        keep_fresh(mirrors, config.mirrors.every_minutes)
    build_server(config).run("stdio")


if __name__ == "__main__":
    main(sys.argv[1:])
