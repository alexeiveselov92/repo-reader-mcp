# CLAUDE.md — repo-reader-mcp

A read-only MCP server for code in git repositories: files at any ref, history, diffs, blame, search —
for any MCP client and any code host. Open source (Apache-2.0), the author's own project. Its sibling,
`semantic-warehouse-mcp` (databases with a semantic layer), is a separate repository with the same rules.

**Language rule.** The author talks to Claude in Russian — reply in Russian. **Everything written to the
repository is in English**: code, comments, docs, commit messages.

## The goal — the author's; don't reword it

1. Read code **with its git history**, not only `main`: any branch, tag or commit.
2. **Never change anything**: read-only by construction.
3. **Universal**: any MCP client (not tied to one model vendor), any code host, any repository — configured
   in YAML, never written into the code.
4. A company applies it in **its own repositories** (which repositories, tokens, deployment). Nothing of any
   company lives here.

## What a session reads

At the start (`/start` does it): `STATE.md` — where we are; the current milestone's section of
`dev/PLAN.md`. When relevant, by section: `dev/DESIGN.md` (how it works), `dev/DECISIONS.md` (what is
decided, grep it), `dev/RESEARCH.md` (what exists, lessons carried).

**The guide** (`docs/`, contents in `docs/README.md`): read the page of the area you change — and change it with it.

## Who the author is

An analyst, **not a developer**: fluent in SQL and data, not in Python internals. Explain through
**consequences**, not pattern names; mark what the agent does and what the author does by hand; steps by
hand in small batches, then wait for "done". Propose decisions with reasoning — the author decides. No
person-day estimates — sessions. Every session ends with something visible.

## Hard rules

- **No installation in the code.** No company, product, person, host, repository or path of a real
  installation — in code, tests, docs or examples. Examples are made up (`acme/*`, `example.com`). A
  repository is the public's: nothing private ever enters it — no tokens, no company code, no output of a
  real repository.
- **Read-only, by construction.** No tool writes to a repository or a host; no shell; commands from a fixed
  set with allow-listed flags; paths stay inside the repository (`dev/DESIGN.md`, "Safety").
- **Secrets by name.** The configuration names the variable that holds a token; the value never appears in a
  file, a log, an answer or an error.
- **Any client.** Nothing that assumes one vendor's client; stdio and Streamable HTTP; tool annotations
  (`read_only_hint`, `destructive_hint`) on every tool; answers capped.
- **The guide is complete, and lives in `docs/`** — the source of the project's site. Everything a user meets — every
  tool, setting, limit, refusal, supported host or engine — has its page; a change that alters what a user sees or does
  updates that page **in the same commit**. `tests/test_docs.py` fails when a tool has no entry in
  `docs/reference/tools.md`. Three readers: people who use it through their agent, people who run it, people who
  contribute. Design, plans, decisions and research live in `dev/`, never on the site.
- **Written fresh.** The author's earlier company platform informs the design (`dev/RESEARCH.md`); its code
  is not copied here.

## The site and hosting

- **The site** is built from `docs/` with Astro + Starlight in `website/` — the pattern of the author's detectkit
  (`../detectkit/website` when the author's repositories sit side by side: its `sync-docs` script, its Dockerfile, its
  `website.yml` workflow). It comes right after remote repositories (`dev/PLAN.md`, milestone 3), so the guide is read
  on the web from the shared server on.
- **Hosting is the author's pipelab** (`../pipelab` beside it — private, with its own `CLAUDE.md`): a Docker Compose
  service behind Traefik per site and per server instance, secrets prefixed in GitHub, a `deploy-<name>.yml` that
  redeploys on this project's `repository_dispatch`. A change there follows pipelab's own rules — read its `CLAUDE.md`
  first.
- Any other installation runs the published image its own way; nothing here assumes pipelab.

## Where requirements come from

A company that applies this server keeps its own inputs — its data model, the registry this server must be able to
express, its gateway — in its own repositories. When the author works from such a company's workspace, the parent
`CLAUDE.md` of that workspace points at them. Read them for **requirements**; never copy their names, hosts, tables,
numbers or rules here — generalise, and show it with made-up examples.

## Quality

- **Verify it yourself** — tests on made-up repositories the tests build (real git, no network), and a real
  MCP client answering through the server. "Should work" is not a report.
- **A protection gets a test that fails when it is removed** — break it, see the test fail, put it back.
- **Re-read your own code.** A second, refuting reader for anything about safety.

## Session cycle

`/start` at the beginning, `/close` at the end.

1. Read `STATE.md` and the current milestone in `dev/PLAN.md`; agree the session's plan in one paragraph.
2. Do it; show the result (a real agent's answer, numbers).
3. **Rewrite `STATE.md` entirely** (not append; under 100 lines); one line per change in `CHANGELOG.md`;
   decisions in `dev/DECISIONS.md`; progress marked in `dev/PLAN.md`.
4. Commit; ask about pushing — the author works from several computers.

**All context lives in this repository — nothing in Claude's local memory** (the author's rule;
`"autoMemoryEnabled": false` in `.claude/settings.json`). **A push is part of passing context**: the author moves
between computers, and an unpushed `STATE.md` doesn't exist on the next one. **One session at a time, on `main`** —
subagents in the same tree when parallelism helps; no worktrees or long-lived branches (`STATE.md` and `CHANGELOG.md`
never merge peacefully).

## Commands

| Command | What |
|---|---|
| `uv sync` | the environment (Python 3.12, from `.python-version`) |
| `uv run pytest` | the tests |
| `uv run ruff check . && uv run ruff format --check .` | lint and format |
| `uv run repo-reader-mcp` | the server over stdio |

## Shell

Write files with the Write and Edit tools, not through the shell. Temporary files go to the session's
scratch dir or `/tmp`, never into the repository tree.
