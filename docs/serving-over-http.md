# Running it for a team

Over stdio, each person's agent starts its own server. For a team, run **one** server on a shared machine and let
everyone's agents connect to it over **Streamable HTTP**: one set of mirrors, one configuration, one token to the code
hosts — and nothing to install on people's computers.

```bash
export REPO_READER_MCP_TOKEN=…        # the bearer token clients will send
export GITHUB_TOKEN=…                 # the read-only token for the code host, as over stdio
repo-reader-mcp --config config.yaml --http 0.0.0.0:8000
```

```yaml
# config.yaml
repositories:
  - github: acme/shop-*
    token_env: GITHUB_TOKEN

http:
  token_env: REPO_READER_MCP_TOKEN    # every request carries `Authorization: Bearer <its value>`
```

The server answers at `/mcp` on that address (`--http 8000` alone listens on `127.0.0.1`). It lists groups and syncs
mirrors in the background, as over stdio; every person's agent reads the same mirrors.

## Who may call

- **A bearer token** — `http.token_env` names the variable that holds it. A request without it, or with another, is
  answered `401` and nothing else. The token is compared in constant time, so how long a refusal takes tells nothing
  about it.
- **A gateway in front** — `http.behind_gateway: true` when your organisation's gateway (an MCP gateway, a proxy with
  single sign-on) checks who calls and only it can reach the server.

On any address other than exactly `127.0.0.1`, `::1` or `localhost` one of the two is required: the server refuses to
start open to anyone who can reach its port. On those three no token is needed — that is one person's computer — and
the server answers only requests addressed to it by those names, so a web page can't reach it through a crafted domain
name.

The server speaks plain HTTP. Put TLS in front of it — a reverse proxy (nginx, Caddy, Traefik) or your gateway — and
route `/mcp` to it without a redirect: clients don't follow one that leaves the address they were given. A proxy on the
same machine may forward to `127.0.0.1` with its own host name (`code.example.com`): with a token or
`behind_gateway: true` the server answers any host name — the token, or the gateway, is what keeps others out.

## Connecting an agent

Any MCP client that takes a URL and a header connects:

```bash
claude mcp add --transport http repo-reader https://code.example.com/mcp \
  --header "Authorization: Bearer $REPO_READER_MCP_TOKEN"
```

or, in a client's JSON configuration:

```json
{
  "mcpServers": {
    "repo-reader": {
      "type": "http",
      "url": "https://code.example.com/mcp",
      "headers": { "Authorization": "Bearer <the token>" }
    }
  }
}
```

Checked with Claude Code and with the [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
(`npx @modelcontextprotocol/inspector --cli https://code.example.com/mcp --transport http --header "Authorization:
Bearer …" --method tools/list`).

## How it answers

- **No session between requests.** Each request is answered on its own — the server keeps nothing about a client — so
  it can be restarted, or run as several copies behind a load balancer, without clients noticing.
- **Plain JSON answers**, not event streams: what gateways and proxies pass through unchanged.
- **Request ids as strings or numbers**, answered as they were sent — gateways often send strings.

## In a container, behind a gateway

The [container image](running-in-a-container.md) serves this way by default. `/health` answers a readiness probe without
the token, and that page says how to put the server behind an MCP gateway.

## Not yet

One token for everyone: no per-person tokens or access rights per repository. Everyone who may call reads every
repository the configuration serves; a gateway in front decides who may call.
