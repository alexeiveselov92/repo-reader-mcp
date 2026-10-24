# repo-reader-mcp

A read-only [MCP](https://modelcontextprotocol.io) server that lets any AI agent read and search code
in git repositories — files at any branch, tag or commit, the history, diffs, blame and search across
many repositories — without ever changing them.

> **Status: pre-alpha, being designed.** Nothing here is ready to use yet. The plan is in
> [docs/PLAN.md](docs/PLAN.md), the design in [docs/DESIGN.md](docs/DESIGN.md).

## Why

Agents answer questions about code better when they can read it the way a developer does: open a file
at the commit that matters, follow a change through the history, compare a branch with `main`, see who
wrote a line and why. Most git MCP servers work on one local checkout and can write to it. This one is
built to be pointed at many repositories — local folders or remote hosts — and to be safe to hand to a
whole team.

## What it will do

- **Read** a file, a folder, any branch, tag or commit — not only the default branch.
- **History**: commits of a repository or a path, a commit with its diff, a diff between two refs, blame.
- **Search** across all configured repositories at once, and `grep` inside one.
- **Any code host**: local paths, GitHub, GitLab, Bitbucket, any git server — mirrored on a schedule,
  fetching only what is read.
- **Read-only by construction**: no command that writes, no shell; secrets found in files are hidden
  before an agent sees them; answers sized for what clients accept.
- **Any MCP client**: stdio for a local agent, Streamable HTTP for a shared server — Claude, ChatGPT,
  Cursor, Codex, any client that speaks MCP.

## Configuration (planned)

One YAML file names the repositories and what to take from them; secrets are named, never written in it.
A draft is in [examples/config.example.yaml](examples/config.example.yaml).

## Development

Python 3.12, [uv](https://docs.astral.sh/uv/), the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run repo-reader-mcp            # the server over stdio
```

## License

[Apache-2.0](LICENSE).
