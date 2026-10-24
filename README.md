# repo-reader-mcp

A read-only [MCP](https://modelcontextprotocol.io) server that lets any AI agent read and search code
in git repositories — files at any branch, tag or commit, the history, diffs, blame and search across
many repositories — without ever changing them.

> **Status: pre-alpha.** It reads local repositories, and remote ones it mirrors from any git host — any branch, tag
> or commit, history, diffs, blame — from a clone of this source ([getting started](docs/getting-started.md)). Groups
> of repositories, a shared server over HTTP, search and a published package are next: the plan is in
> [dev/PLAN.md](dev/PLAN.md), the design in [dev/DESIGN.md](dev/DESIGN.md).

## Why

Agents answer questions about code better when they can read it the way a developer does: open a file
at the commit that matters, follow a change through the history, compare a branch with `main`, see who
wrote a line and why. Most git MCP servers work on one local checkout and can write to it. This one is
built to be pointed at many repositories — local folders or remote hosts — and to be safe to hand to a
whole team.

## What it will do

- **Read** a file, a folder, any branch, tag or commit — not only the default branch.
- **History**: commits of a repository or a path, a commit with its diff, a diff between two refs, blame.
- **Guidance for agents**: a repository's `AGENTS.md`, `CLAUDE.md`, rules and skills reach the agent reading it
  — plus what the people who run the server add, from its configuration or from another repository.
- **Search** across all configured repositories at once, and `grep` inside one.
- **Any code host**: local paths, GitHub, GitLab, Bitbucket, any git server — mirrored on a schedule,
  fetching only what is read.
- **Read-only by construction**: no command that writes, no shell; secrets found in files are hidden
  before an agent sees them; answers sized for what clients accept.
- **Any MCP client**: stdio for a local agent, Streamable HTTP for a shared server — Claude, ChatGPT,
  Cursor, Codex, any client that speaks MCP.

## Configuration

One YAML file names the repositories and what to take from them; secrets are named, never written in it.
An example is in [examples/config.example.yaml](examples/config.example.yaml); every key is in
[docs/reference/configuration.md](docs/reference/configuration.md). The documentation starts at [docs/](docs/README.md).

## Development

Python 3.12, [uv](https://docs.astral.sh/uv/), the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run repo-reader-mcp --config my-config.yaml --check                 # check a configuration
uv run repo-reader-mcp --config my-config.yaml --sync                  # bring the mirrors up to date once
uv run repo-reader-mcp --config my-config.yaml                         # the server over stdio
```

## License

[Apache-2.0](LICENSE).
