# repo-reader-mcp documentation

The documentation for people who use and run repo-reader-mcp. This folder is the **single source**: the site
(Astro + Starlight, in `website/`) is built from these files and carries every one of them — a test fails otherwise;
edit them here, never in the site.

How the project is built and planned is not here: that is `dev/` (design, plan, decisions, research).

## Pages

- [Getting started](getting-started.md) — run it from a clone, say which repositories it reads, connect it to an agent,
  ask.
- [Remote repositories](remote-repositories.md) — repositories on GitHub, GitLab or any git server: mirrors, what they
  hold, how they stay fresh, groups of repositories by a pattern, tokens per host.
- [Running it for a team](serving-over-http.md) — one shared server over Streamable HTTP: a bearer token or a gateway,
  connecting agents.
- **Reference**
  - [Tools](reference/tools.md) — every tool, its inputs and its answer.
  - [Configuration](reference/configuration.md) — the file, every key, the patterns of `include` / `exclude`, limits.
  - [Guidance for agents](reference/guidance.md) — the rules a repository carries for agents (`AGENTS.md`,
    `CLAUDE.md`, rules, skills) and what the configuration adds; how they reach an agent.
  - [Safety](reference/safety.md) — what it never does, and what it doesn't do yet.

Planned, each written with the change that makes it true: search and grep; a container image; a contributing page.

Three readers: people who use it through their agent (getting started, guides), people who run it (guides,
reference), people who contribute (a contributing page). A page is written in the same commit as the change that makes
it true; a tool without its reference entry fails the tests.
