# Research — what exists, and what we take from it

Read 2026-10-24. Re-check before a design decision that leans on it.

## Git MCP servers today

Most work on one local checkout and are read-only by convention (listed on Glama):
[git-insights-mcp, MCP Git Enhanced, git-context-mcp, Git Forensics MCP, Git Analytics MCP Server](https://glama.ai/mcp/servers/@davidorex/git-forensics-mcp/blob/a7bf43035f0a93d511532959dd2ecb480c10b399/README.md) —
commits, diffs, branch comparison, blame, churn. None mirrors many remote repositories, searches across them,
or hides secrets before an agent sees a file. The hosts' own servers (GitHub's, GitLab's) cover issues and
pull requests and need each person's token.

**Our place:** many repositories, any host, any ref, search across them, safe to share — read-only by
construction rather than by convention.

## Lessons carried from the author's earlier platform (design, not code)

- A partial clone holds the whole history at a fraction of the size; contents are fetched for what is read.
  Commands that silently fetch on a partial clone must be avoided (`cat-file` on a missing object, diffs,
  rename detection) — count and read through commands over trees.
- `grep` for agents is powerful and cheap (fewer calls than search alone, measured) when it is an allow-list
  of reading commands with no shell.
- Search over a code index (Zoekt) answered 50 people at once in ~0.1 s on ~80 repositories.
- Secrets live in code: gitleaks' rules plus rules for passwords written as prose; a value hidden whole.
- A repository that holds what must never be read is taken by an allow-list (`include`), never by
  `exclude` alone.
- Clients cut long answers (Claude Code near 25,000 tokens): every answer is capped and says so.
- Gateways in front of MCP servers send string JSON-RPC ids; a server that only answers numbers stalls them.

## The MCP Python SDK

2.x (2.3.0 on 2026-10-24): `mcp.server.mcpserver.MCPServer` (FastMCP renamed), tool annotations
`read_only_hint` / `destructive_hint`, `mcp.Client` connects to a server in-process for tests, over stdio, or
over Streamable HTTP.
