# Where we are

> Rewritten entirely at the end of every session by `/close`. Don't append. Under 100 lines.

**Updated:** 24 October 2026.

**Current milestone: 6 — ready to deploy** (`dev/PLAN.md`). Done: 1 (local repositories), 2 (remote repositories,
groups, Streamable HTTP, links to hosts), 3 (the docs site), 4 (search and safety), 5 (the site's landing page);
from 7, **0.1.0 is on PyPI** (`uvx repo-reader-mcp`).

## What exists

- **Twelve read-only tools** (`src/repo_reader_mcp/tools.py`): `list_repos`, `list_refs`, `read_file`, `list_files`,
  `log`, `show_commit`, `diff`, `blame`, `search` (across repositories), `grep` (one repository, any ref, context),
  `read_guidance`, `about`. Answers name the commit, are capped, link to the host's page.
- **Repositories**: local (`path`); mirrored (`url`: bare partial clones, a token by variable name, synced on a
  schedule, contents of served paths only, older contents fetched on purpose); groups (`github: owner/pattern`,
  `gitlab: group/**/pattern`, `skip`, `host`, `forks`) listed by the host's API before every sync; a catalog replaced
  whole, one set per tool call.
- **Transports**: stdio; Streamable HTTP (`--http [HOST:]PORT`, stateless, JSON) behind `http.token_env` or
  `http.behind_gateway`.
- **Search**: `git grep` over the served files by name, the pattern after `-e`; no index (0.2–0.4 s over 18 repos).
- **Secrets** (`secrets.py`): every answer and error passes a filter last (tokens, URL passwords, key material, values
  of settings named for secrets, passwords in prose → `[hidden: …]`, the count said); key blocks hidden whole; no agent
  pattern matched again on hidden text, so a guess can't be confirmed. Credential files never served nor fetched
  unless `serve_credential_files: true`.
- **Guidance**: a repository's own rules (all, none, or `own: [patterns]`), the operators' text and files, `from`
  another repository.
- **Release**: 0.1.0 on PyPI by trusted publishing (`publish` workflow on a tag `v*`; tests first; the tag must name
  the version). **The site**: https://rrm.pipelab.dev (Astro + Starlight; a landing page like detectkit's; redeployed
  by pipelab on every push; `repo-reader.pipelab.dev` answers 301 there).

## How it was verified

- 271 tests on made-up repositories and hosts (real git, no network); ruff clean; CI green (lint, tests, site build).
- Every protection taken out in turn — 92 across the mirrors, groups, HTTP, search, secrets and the reviews' fixes:
  its test failed each time (scripts in the session's scratch, not kept).
- Three refuting reviews by a second agent: 11 + 10 + 11 findings (one a way to read a secret out through a regex) —
  all closed with tests.
- Real clients: Claude Code over stdio and HTTP, the MCP Inspector over both; the wheel run through `uvx` from PyPI.
- A real installation (a company's, in its own repository): ~90 repositories mirrored in ~2 minutes, reads equal to
  `git show`, a corpus taken by `include` with nothing else fetched, agents tracing questions across services and into
  the warehouse — its facts checked by its own script. What it needed came back here as general features (groups,
  `own` patterns, the credential rule's speed).

## Next step — milestone 6

Ready to deploy: a container image of the server on GHCR (built by CI; the configuration and the mirrors' folder
mounted, secrets by environment), a health endpoint for a gateway or an orchestrator, the guide's page on running it in
a container behind an MCP gateway. Then **0.2.0** — it carries `own` patterns and the fixes since 0.1.0, which the
installation needs before it deploys.

## What the author needs to do

- Nothing blocks milestone 6. A new version: bump `version` in `pyproject.toml`, `uv lock`, a CHANGELOG line, push a
  tag `v<version>`.

## Don't

- Don't write a real company, product, repository or path anywhere here — the repository is public.
- Don't add a tool without `read_only_hint=True`, `destructive_hint=False`, and its entry in `docs/reference/tools.md`.
- Don't add a page to `docs/` without listing it in `website/scripts/sync-docs.mjs` and the sidebar.
- Don't pass an agent's ref to git: resolve it to a commit id first; an agent's pattern goes after `-e` only.
- Don't give git a path pattern for what include / exclude decide — give it the served files by name.
- Don't match an agent's pattern again on hidden text: decide by the hidden spans of the line as written.
- Don't add a protection without a test that fails when it is removed.
