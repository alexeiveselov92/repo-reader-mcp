# Getting started

repo-reader-mcp lets an AI agent read git repositories — any branch, tag or commit, the history, diffs, blame — and
never change them. This page runs it from a clone of its source, over stdio, for one person's agent. (A published
package and a container image come later.)

## 1. Get it

You need git 2.30 or newer, Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/alexeiveselov92/repo-reader-mcp.git
cd repo-reader-mcp
uv sync
```

## 2. Say which repositories it reads

Write a configuration file, say `~/repo-reader.yaml` ([every key](reference/configuration.md)):

```yaml
repositories:
  - name: shop-backend
    path: ~/code/shop-backend
    description: The shop's backend — orders, payments, the public API.
    exclude: ["*.pem", "*.env"]
```

Check it:

```bash
uv run repo-reader-mcp --config ~/repo-reader.yaml --check
```

## 3. Connect it to your agent

**Claude Code:**

```bash
claude mcp add repo-reader -- uv --directory /path/to/repo-reader-mcp run repo-reader-mcp --config ~/repo-reader.yaml
```

**Any other MCP client** (Claude Desktop, Cursor, Codex, …) takes the same command in its MCP settings — for example:

```json
{
  "mcpServers": {
    "repo-reader": {
      "command": "uv",
      "args": ["--directory", "/path/to/repo-reader-mcp", "run", "repo-reader-mcp", "--config", "/home/you/repo-reader.yaml"]
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
