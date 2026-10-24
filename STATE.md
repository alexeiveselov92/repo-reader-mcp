# Where we are

> Rewritten entirely at the end of every session by `/close`. Don't append. Under 100 lines.

**Updated:** 24 October 2026 (mid-session: the author asked to keep working in the same session).

**Current milestone: 6 — ready to deploy** (`dev/PLAN.md`). Milestones 1 (local repositories),
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

## Next step

- **0.1.0 on PyPI**: everything is ready (`publish` workflow, trusted publishing, the wheel checked through `uvx`); the
  tag `v0.1.0` is pushed once the author adds the pending publisher on PyPI (`repo-reader-mcp`, owner
  `alexeiveselov92`, workflow `publish.yml`, environment `pypi`).
- **Milestone 6 — ready to deploy**: a container image on GHCR (built by CI), a health endpoint, the guide's page on
  running it in a container behind an MCP gateway — proved by the company installation kept in its own repository.
  The landing page (milestone 5) is done.

## What the author needs to do

- Nothing blocks the library. The installation's work (its configuration, a read-only token for its host, its
  gateway) happens in that installation's own repository and session.

## Don't

- Don't write a real company, product, repository or path anywhere here — the repository is public.
- Don't add a tool without `read_only_hint=True`, `destructive_hint=False`, and its entry in `docs/reference/tools.md`.
- Don't add a page to `docs/` without listing it in `website/scripts/sync-docs.mjs` and the sidebar.
- Don't pass an agent's ref to git: resolve it to a commit id first; an agent's pattern goes after `-e` only.
- Don't give git a path pattern for what include / exclude decide — give it the served files by name.
- Don't match an agent's pattern again on hidden text: decide by the hidden spans of the line as written.
- Don't add a protection without a test that fails when it is removed.
