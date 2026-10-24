# Where we are

> Rewritten entirely at the end of every session by `/close`. Don't append. Under 100 lines.

**Updated:** 24 October 2026.

**Current milestone: 1 — one local repository, read-only** (`dev/PLAN.md`). Milestone 0 (groundwork) is done.

## What exists

- The repository (public, Apache-2.0), README; `dev/` — design, plan, decisions, research; `docs/` — the public
  documentation's source (the site comes in a later milestone, hosted through the author's pipelab); the session
  flow (`CLAUDE.md`, `/start`, `/close`).
- A skeleton: the server over stdio (`uv run repo-reader-mcp`) with one tool, `about`; its tests through the
  SDK's in-process client (every tool read-only; `about` answers); ruff; CI on GitHub Actions.
- A draft of the configuration: `examples/config.example.yaml`.

## Next step

Milestone 1: the YAML configuration and its check, then the reading tools over one local repository
(`list_repos`, `list_refs`, `read_file`, `list_files`, `log`, `show_commit`, `diff`, `blame`) — tested on
made-up repositories the tests build, then real Claude Code over stdio.

## What the author needs to do

Nothing blocks milestone 1. Open Claude Code in this repository's folder and run `/start`.

## Don't

- Don't write a real company, product, repository or path anywhere here — the repository is public.
- Don't add a tool without `read_only_hint=True`, `destructive_hint=False` (a test refuses it).
- Don't run git commands that fetch contents on a partial mirror by accident (`dev/DESIGN.md`, "Safety").
