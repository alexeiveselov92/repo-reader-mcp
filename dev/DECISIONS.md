# Decisions

What is decided and why. Newest at the bottom; grep it.

## 2026-10-24 · An open-source, universal, read-only MCP for code

**Decision** (the author). A separate open-source project under the author's own GitHub, not any
company's: an MCP server for reading code with its git history, any branch, read-only — for any MCP client
(not tied to one model vendor) and any code host. A company's use of it — which repositories, tokens,
deployment — lives in that company's own repositories as configuration; nothing of any company is written
here.

**Why.** One tool many teams can use, configured rather than rewritten; the author's earlier
company-internal platform proved the parts (mirrors, search, safe grep, secret hiding) and showed they are
general.

## 2026-10-24 · The name keeps `mcp`; the documentation and hosting follow the author's own projects

- **The name is `repo-reader-mcp`** — the author's rule: `mcp` in the name and a meaning plain at a glance (the `-kit` names of
  the author's other projects were weighed and set aside); free on PyPI.
- **Documentation and hosting** as in the author's detectkit and pipelab: `docs/` the single source of a site built
  with Astro + Starlight; the site and an instance of the server deployed by `alexeiveselov92/pipelab`
  (`dev/DESIGN.md`, "Documentation, distribution and hosting"). Internal design, plan, decisions and research moved to
  `dev/` the same day, so the site never publishes them.

## 2026-10-24 · Python, the official MCP SDK, Apache-2.0, written fresh

- **Python 3.12 with uv**, the official MCP Python SDK (2.x: `MCPServer`, the in-process `Client` for tests).
  Installed with one command (`uvx`); the same stack as its sibling, semantic-warehouse-mcp.
- **Apache-2.0**: an explicit patent grant; the license companies take in most easily.
- **Written fresh**: the earlier platform's code belongs to the company it was written for. Its lessons are
  carried as design ([DESIGN.md](DESIGN.md), "Safety"), not as code.
