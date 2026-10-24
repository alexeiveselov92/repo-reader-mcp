# repo-reader-mcp documentation

The documentation for people who use and run repo-reader-mcp. This folder is the **single source**: the site
(Astro + Starlight, planned — `dev/PLAN.md`) is built from these files; edit them here, never in the site.

How the project is built and planned is not here: that is `dev/` (design, plan, decisions, research).

## Pages

Written now: [Reference — tools](reference/tools.md). Planned, each written with the change that makes it true:

- **Getting started** — install (`uvx repo-reader-mcp`), connect it to an MCP client (Claude Code, Claude, ChatGPT,
  Cursor, Codex), a first question about a repository.
- **Guides** — configuring repositories (local and remote, refs, `include` / `exclude`, tokens by name); running it
  for a team (Streamable HTTP, a container); what an agent can ask.
- **Reference** — every tool, its inputs and answers; the configuration file; limits; safety (what it never does).

Three readers: people who use it through their agent (getting started, guides), people who run it (guides,
reference), people who contribute (a contributing page). A page is written in the same commit as the change that makes
it true; a tool without its reference entry fails the tests.
