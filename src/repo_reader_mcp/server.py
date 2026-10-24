"""The MCP server. Every tool is read-only and says so (dev/DESIGN.md, "Safety")."""

from __future__ import annotations

import argparse
import hmac
import logging
import os
import sys

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from . import __version__
from .catalog import Catalog, keep_fresh, resolve
from .config import Config, ConfigError, load_config
from .guidance import gather, out_of_reach
from .hosts import HostError
from .mirror import SyncError, sync_all
from .repository import ReadError
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


def build_server(config: Config | None = None, catalog: Catalog | None = None) -> MCPServer:
    """The server with its tools — built fresh, so tests and transports each get their own."""
    config = config or Config()
    catalog = catalog if catalog is not None else Catalog(config)
    server = MCPServer(name="repo-reader-mcp", version=__version__, instructions=INSTRUCTIONS)

    @server.tool(annotations=READ_ONLY)
    def about() -> dict:
        """What this server is and its version. Call it to check the connection."""
        return {
            "name": "repo-reader-mcp",
            "version": __version__,
            "status": "pre-alpha: local and mirrored remote repositories",
            "read_only": True,
            "repositories": len(catalog.listed()),
        }

    register(server, config, catalog)
    return server


def check(source: str, config: Config) -> None:
    """What `--check` prints: the repositories served — a remote one's host asked whether it answers, a group's host
    asked what it lists — the guidance each carries, and guidance agents won't get. Nothing is written."""
    catalog = Catalog(config)
    count, groups = len(config.repositories), len(config.groups)
    served = f"{count} repositor{'y' if count == 1 else 'ies'}" if count or not groups else ""
    served += (" and " if served and groups else "") + (f"{groups} group{'s' if groups != 1 else ''}" if groups else "")
    print(f"The configuration {source} is good — it serves {served}:")
    for repo in config.repositories:
        mirror = catalog[repo.name].mirror
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
            docs = gather(repo, config.guidance, catalog).docs
        except ReadError as error:
            print(f"    guidance can't be read: {error}")
            continue
        if docs:
            print(f"    guidance: {', '.join(doc.name for doc in docs)}")
        for path in out_of_reach(catalog[repo.name]):
            print(
                f"    warning: {path} is guidance for agents, but outside its include / exclude — agents won't get it"
            )
    for group in config.groups:
        print(f"  {group.label}  {group.host.web}")
        try:
            listing = resolve(group)
        except HostError as error:
            print(f"    host: can't list it: {error}")
            continue
        names = len(listing.members)
        print(f"    the host lists {names} repositor{'y' if names == 1 else 'ies'} it takes:")
        others = {name: repo for name, repo in catalog.items() if repo.config.group != group.label}
        for member in listing.members:
            clash = catalog.clash(group, member, others)
            if clash:
                print(f"    {member.name}  {member.path}  (left out: {clash})")
                continue
            taken = catalog.get(member.name)
            made = taken is not None and taken.mirror is not None and taken.mirror.ready
            print(f"    {member.name}  {member.path}  ({'mirror made' if made else 'not mirrored yet'})")
        for line in listing.left_out:
            print(f"    left out: {line}")


def sync_once(config: Config) -> bool:
    """What `--sync` prints: every group listed and every mirror brought up to date once, and how; whether all of
    them worked."""
    catalog = Catalog(config)
    if not config.groups and not catalog.mirrors():
        print("No remote repositories are configured: nothing to sync.")
        return True
    worked_all = True
    for group, outcome, worked in catalog.refresh():
        print(f"  {group.label}: {outcome if worked else 'listing it failed: ' + outcome}")
        worked_all = worked_all and worked
    for clash in catalog.clashes:
        print(f"  {clash}")
    for mirror, outcome, worked in sync_all(catalog.mirrors()):
        print(f"  {mirror.name}: {outcome if worked else 'failed: ' + outcome}")
        worked_all = worked_all and worked
    return worked_all


# The machine's own addresses, for serving with no token: exactly those the SDK guards against DNS rebinding (it answers
# only requests naming them as the host) — not every loopback address, which it wouldn't guard.
LOOPBACK = ("127.0.0.1", "localhost", "::1")


class BearerToken:
    """Every request carries `Authorization: Bearer <token>`, or is answered 401 — compared in constant time, so the
    time an answer takes tells nothing about the token."""

    def __init__(self, app, token: str):
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            given = b""
            for key, value in scope.get("headers", ()):
                if key.lower() == b"authorization":
                    given = value
            if not hmac.compare_digest(given, self.expected):
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"www-authenticate", b'Bearer realm="repo-reader-mcp"'),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": b'{"error": "a bearer token is needed"}'})
                return
        await self.app(scope, receive, send)


def http_app(server: MCPServer, config: Config, host: str):
    """The server as an ASGI app over Streamable HTTP at `/mcp`: no session kept between requests, plain JSON
    answers; behind the bearer token when the configuration names one. A non-loopback address with neither a token
    nor `behind_gateway: true` is refused — anyone who reaches the port could read the code."""
    guarded = bool(config.http.token_env or config.http.behind_gateway)
    if not guarded and host not in LOOPBACK:
        raise ConfigError(
            "http",
            [
                f"serving on {host} lets anyone who reaches it read the code: name the variable holding a bearer "
                "token in `http: token_env`, or say `http: behind_gateway: true` when a gateway in front checks who "
                "calls"
            ],
        )
    # Guarded by a token or a gateway, any host name is answered — a proxy on the same machine forwards its own; open on
    # the machine's own address, only that address's names are (the SDK's guard against DNS rebinding).
    security = TransportSecuritySettings(enable_dns_rebinding_protection=False) if guarded else None
    app = server.streamable_http_app(stateless_http=True, json_response=True, host=host, transport_security=security)
    if config.http.token_env:
        token = os.environ.get(config.http.token_env, "")
        if not token:
            raise ConfigError("http", [f"the variable {config.http.token_env} is not set in the server's environment"])
        return BearerToken(app, token)
    return app


def _address(value: str) -> tuple[str, int]:
    host, _, port = value.rpartition(":")
    host = host.strip("[]") or "127.0.0.1"
    if not port.isdigit() or not 0 < int(port) < 65536:
        raise argparse.ArgumentTypeError(f"`{value}` is not [HOST:]PORT, like 8000 or 0.0.0.0:8000")
    return host, int(port)


def main(argv: list[str] | None = None) -> None:
    """The console entry point: check the configuration, then serve over stdio (or Streamable HTTP) — listing groups
    and syncing mirrors in the background."""
    parser = argparse.ArgumentParser(prog="repo-reader-mcp", description=__doc__)
    parser.add_argument(
        "--config", default=os.environ.get(CONFIG_VARIABLE), help=f"the configuration file (or set {CONFIG_VARIABLE})"
    )
    parser.add_argument("--check", action="store_true", help="check the configuration, list what it serves, and exit")
    parser.add_argument("--sync", action="store_true", help="list every group and sync every mirror once, and exit")
    parser.add_argument(
        "--http",
        metavar="[HOST:]PORT",
        type=_address,
        help="serve over Streamable HTTP at /mcp on this address (default host 127.0.0.1) instead of stdio",
    )
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
    logging.getLogger("mcp").setLevel(logging.WARNING)  # the SDK's own lines, one per HTTP request
    if args.sync:
        if not sync_once(config):
            parser.exit(1)
        return
    catalog = Catalog(config)
    server = build_server(config, catalog)
    if args.http:
        host, port = args.http
        try:
            app = http_app(server, config, host)
        except ConfigError as error:
            parser.exit(2, f"repo-reader-mcp: {error}\n")
    if config.groups or catalog.mirrors():
        keep_fresh(catalog, config.mirrors.every_minutes)
    if not args.http:
        server.run("stdio")
        return
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info", server_header=False)


if __name__ == "__main__":
    main(sys.argv[1:])
