# Getting started

repo-reader-mcp lets an AI agent read git repositories — any branch, tag or commit, the history, diffs, blame — and
never change them. This page runs it over stdio, for one person's agent; for a team, [run it over
HTTP](serving-over-http.md) or [in a container](running-in-a-container.md).

## 1. Get it

You need git 2.31 or newer and Python 3.12 or newer. With [uv](https://docs.astral.sh/uv/), there is nothing to install:
`uvx repo-reader-mcp` fetches it and runs it. Or install it into an environment of your own:

```bash
pip install repo-reader-mcp
```

(From a clone of its source: `uv sync`, then `uv run repo-reader-mcp …` — what contributors do.)

## 2. Say which repositories it reads

Write a configuration file, say `~/repo-reader.yaml` ([every key](reference/configuration.md)):

```yaml
repositories:
  - name: shop-backend
    path: ~/code/shop-backend
    description: The shop's backend — orders, payments, the public API.
    exclude: ["*.pem", "*.env"]

  - url: https://github.com/acme/shop-frontend.git   # a repository on a host: the server keeps a mirror of it
    token_env: GITHUB_TOKEN                          # for a private one: the variable holding a read-only token
```

A repository on a host is [mirrored](remote-repositories.md) on your machine — its history, and the contents of the
files it serves. Check the file (for a remote repository, it also asks the host whether it answers):

```bash
uvx repo-reader-mcp --config ~/repo-reader.yaml --check
```

The server makes the mirrors in the background when it starts; to make them now and see how it went, run it once with
`--sync`.

## 3. Connect it to your agent

**Claude Code:**

```bash
claude mcp add repo-reader -- uvx repo-reader-mcp --config ~/repo-reader.yaml
```

**Any other MCP client** (Claude Desktop, Cursor, Codex, …) takes the same command in its MCP settings — for example:

```json
{
  "mcpServers": {
    "repo-reader": {
      "command": "uvx",
      "args": ["repo-reader-mcp", "--config", "/home/you/repo-reader.yaml"]
    }
  }
}
```

## 4. Ask

- *"Which repositories can you read? What changed on `main` this week?"*
- *"Show me `src/orders/service.py` as it was at `v2.3.0`, and what changed in it since."*
- *"What does the branch `feature/refunds` change compared with `main`?"*
- *"Who wrote the retry logic in `src/payments/client.py`, and why?"*

The agent calls the [tools](reference/tools.md); every answer names the commit it was read at.

## For a team

One server on a shared machine can serve everyone's agents over HTTP, behind a token — and a whole group of
repositories can be named by a pattern (`github: acme/shop-*`) instead of one by one: [running it for a
team](serving-over-http.md), [groups](remote-repositories.md#groups).
