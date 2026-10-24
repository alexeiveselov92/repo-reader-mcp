# Where we are

> Rewritten entirely at the end of every session by `/close`. Don't append. Under 100 lines.

**Updated:** 24 October 2026 (mid-session: the author asked to keep working in the same session).

**Current milestone: 5 — the author's server instance** (`dev/PLAN.md`). Milestones 1 (local repositories),
2 (remote repositories, groups, HTTP, links), 3 (the docs site, live at https://repo-reader.pipelab.dev) and
4 (search and safety) are done.

## What exists

- **Eleven read-only tools** at any ref (`src/repo_reader_mcp/tools.py`): `list_repos`, `list_refs`, `read_file`,
  `list_files`, `log`, `show_commit`, `diff`, `blame`, `search` (across repositories), `grep` (one repository, any
  ref, context), `read_guidance`; plus `about`. Answers name the commit, are capped, link to the host's page.
- **Repositories**: local (`path`); mirrored (`url`: bare partial clones, a token by variable name, synced on a
  schedule, contents of served paths only, older contents fetched on purpose); groups (`github: owner/pattern`,
  `gitlab: group/**/pattern`, `skip`, `host`, `forks`) listed by the host's API before every sync; a catalog replaced
  whole, one set per tool call.
- **Transports**: stdio; Streamable HTTP (`--http [HOST:]PORT`, stateless, JSON) behind `http.token_env` or
  `http.behind_gateway`.
- **Search**: `git grep` given the served files by name, the pattern after `-e`; no index (0.2–0.4 s over 18 repos).
- **Secrets** (`secrets.py`): every answer and error passes a filter last — providers' tokens, URL passwords, key
  material (one-line keys too), values of settings named for secrets, passwords in prose → `[hidden: …]`, the count
  said; key blocks hidden whole in files, blame, search and diffs; no agent pattern is matched again on hidden text,
  so a guess can't be confirmed. Files named for credentials (`.env`, `*.pem`, `id_rsa`, …) never served nor fetched
  unless `serve_credential_files: true`.
- **The guide** (`docs/`) and **the site** (`website/`, redeployed by pipelab on every push to main).

## How it was verified

- 270 tests on made-up repositories and hosts (real git, no network); ruff clean; CI green (lint, tests, site build).
- Every protection taken out in turn — 33 (mirrors), 28 (groups, HTTP), 4 (search), 11 (secrets), 15 (third review):
  its test failed each time (scripts in the session's scratch, not kept).
- Three refuting reviews by a second agent: 11 findings (mirrors), 10 (groups, HTTP), 11 (search, secrets — one a way
  to read a secret out through a regex) — all closed with tests.
- Real clients: Claude Code over stdio and HTTP, the MCP Inspector over both; an 18-repository public GitHub group;
  `search` answered a cross-repository question.

## Next step — milestone 5

An instance of the server in pipelab: a container image of the server (a root `Dockerfile`, pushed to GHCR by a
workflow, like the site's), a `repo-reader-mcp` service with `/mcp` routed without a redirect, its `deploy-*.yml`,
its configuration and token secret in pipelab — for the author's own use and a public demo.

## What the author needs to decide (before milestone 5)

1. **What the instance serves**: the author's own public repositories (this one, detectkit, …), a public demo over
   made-up repositories, or something private — its configuration lives in pipelab, never here.
2. **Who may call it**: a bearer token (the author creates the secret in pipelab's GitHub settings), or open for a
   demo.

## Don't

- Don't write a real company, product, repository or path anywhere here — the repository is public.
- Don't add a tool without `read_only_hint=True`, `destructive_hint=False`, and its entry in `docs/reference/tools.md`.
- Don't add a page to `docs/` without listing it in `website/scripts/sync-docs.mjs` and the sidebar.
- Don't pass an agent's ref to git: resolve it to a commit id first; an agent's pattern goes after `-e` only.
- Don't give git a path pattern for what include / exclude decide — give it the served files by name.
- Don't match an agent's pattern again on hidden text: decide by the hidden spans of the line as written.
- Don't add a protection without a test that fails when it is removed.
