# repo-reader-mcp documentation

The documentation for people who use and run repo-reader-mcp. This folder is the **single source**: the site
(Astro + Starlight, planned — `dev/PLAN.md`) is built from these files; edit them here, never in the site.

How the project is built and planned is not here: that is `dev/` (design, plan, decisions, research).

## Pages (planned)

- **Getting started** — install (`uvx repo-reader-mcp`), connect it to an MCP client (Claude Code, Claude, ChatGPT,
  Cursor, Codex), a first question about a repository.
- **Guides** — configuring repositories (local and remote, refs, `include` / `exclude`, tokens by name); running it
  for a team (Streamable HTTP, a container); what an agent can ask.
- **Reference** — every tool, its inputs and answers; the configuration file; limits; safety (what it never does).

A page is written in the same commit as the change that makes it true.
