# repo-reader-mcp documentation

The documentation for people who use and run repo-reader-mcp. This folder is the **single source**: the site
(Astro + Starlight, planned — `dev/PLAN.md`) is built from these files; edit them here, never in the site.

How the project is built and planned is not here: that is `dev/` (design, plan, decisions, research).

## Pages

- [Getting started](getting-started.md) — run it from a clone, say which repositories it reads, connect it to an agent,
  ask.
- **Reference**
  - [Tools](reference/tools.md) — every tool, its inputs and its answer.
  - [Configuration](reference/configuration.md) — the file, every key, the patterns of `include` / `exclude`, limits.
  - [Guidance for agents](reference/guidance.md) — the rules a repository carries for agents (`AGENTS.md`,
    `CLAUDE.md`, rules, skills) and what the configuration adds; how they reach an agent.
  - [Safety](reference/safety.md) — what it never does, and what it doesn't do yet.

Planned, each written with the change that makes it true: remote repositories and running it for a team (Streamable
HTTP, a container); search and grep; a contributing page.

Three readers: people who use it through their agent (getting started, guides), people who run it (guides,
reference), people who contribute (a contributing page). A page is written in the same commit as the change that makes
it true; a tool without its reference entry fails the tests.
