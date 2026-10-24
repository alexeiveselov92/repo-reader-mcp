# CLAUDE.md — repo-reader-mcp

A read-only MCP server for code in git repositories: files at any ref, history, diffs, blame, search —
for any MCP client and any code host. Open source (Apache-2.0), the author's own project. Its sibling,
`warehouse-mcp` (databases with a semantic layer), is a separate repository with the same rules.

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
`docs/PLAN.md`. When relevant, by section: `docs/DESIGN.md` (how it works), `docs/DECISIONS.md` (what is
decided, grep it), `docs/RESEARCH.md` (what exists, lessons carried).

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
  set with allow-listed flags; paths stay inside the repository (`docs/DESIGN.md`, "Safety").
- **Secrets by name.** The configuration names the variable that holds a token; the value never appears in a
  file, a log, an answer or an error.
- **Any client.** Nothing that assumes one vendor's client; stdio and Streamable HTTP; tool annotations
  (`read_only_hint`, `destructive_hint`) on every tool; answers capped.
- **Written fresh.** The author's earlier company platform informs the design (`docs/RESEARCH.md`); its code
  is not copied here.

## Quality

- **Verify it yourself** — tests on made-up repositories the tests build (real git, no network), and a real
  MCP client answering through the server. "Should work" is not a report.
- **A protection gets a test that fails when it is removed** — break it, see the test fail, put it back.
- **Re-read your own code.** A second, refuting reader for anything about safety.

## Session cycle

`/start` at the beginning, `/close` at the end.

1. Read `STATE.md` and the current milestone in `docs/PLAN.md`; agree the session's plan in one paragraph.
2. Do it; show the result (a real agent's answer, numbers).
3. **Rewrite `STATE.md` entirely** (not append; under 100 lines); one line per change in `CHANGELOG.md`;
   decisions in `docs/DECISIONS.md`; progress marked in `docs/PLAN.md`.
4. Commit; ask about pushing — the author works from several computers.

**All context lives in this repository — nothing in Claude's local memory** (the author's rule).

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
