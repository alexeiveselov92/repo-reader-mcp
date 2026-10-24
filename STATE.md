# Where we are

> Rewritten entirely at the end of every session by `/close`. Don't append. Under 100 lines.

**Updated:** 25 October 2026.

**Current milestone: 6 — ready to deploy, proved by a real installation** (`dev/PLAN.md`). Its first half is done:
the container image, `/health` and the guide's page, released as **0.2.0** (PyPI and GHCR). Its second half: a company
deploying it from its own repository. Done before: 1 (local repositories), 2 (remote repositories, groups, Streamable
HTTP, links to hosts), 3 (the docs site), 4 (search and safety), 5 (the site's landing page).

## What exists

- **Twelve read-only tools** (`src/repo_reader_mcp/tools.py`): `list_repos`, `list_refs`, `read_file`, `list_files`,
  `log`, `show_commit`, `diff`, `blame`, `search` (across repositories), `grep` (one repository, any ref, context),
  `read_guidance`, `about`. Answers name the commit, are capped, link to the host's page. `list_repos` and the
  unknown-repository error name a group no host has listed yet, with the host's error.
- **Repositories**: local (`path`); mirrored (`url`: bare partial clones, a token by variable name, synced on a
  schedule, contents of served paths only); groups (`github: owner/pattern`, `gitlab: group/**/pattern`, `skip`, `host`,
  `forks`) listed by the host's API before every sync; one set per tool call.
- **Transports**: stdio; Streamable HTTP (`--http [HOST:]PORT`, stateless, JSON) behind `http.token_env` or
  `http.behind_gateway`. **`/health`**: `503 {"status":"syncing"}` until the first sync round ends (or at once over a
  kept mirrors folder), then `200 {"status":"ready"}` for good; the one path without the token (exactly it); probes
  left out of the access log.
- **The image** (`Dockerfile`, `Dockerfile.dockerignore`): python 3.12 slim (trixie), git 2.47 (≥ 2.44 asserted) and
  ssh, user `reader` 10001, read-only root with `/tmp` and `/data` writable; configuration at `/config/config.yaml`,
  mirrors at `/data/repo-reader-mcp` (via `XDG_CACHE_HOME`); `CMD --http 0.0.0.0:8000`. A mounted local repository of
  another owner is refused with what to do (`safe.directory` through `GIT_CONFIG_GLOBAL`).
- **CI**: `ci` (lint, tests, site build); `image` (both platforms built and tried by `.github/scripts/try-image.sh` on
  every change; for a tag, published from the same layers as the version and `sha-…`, never `latest`, then the
  published image tried again); `publish` (PyPI on a tag); `website` (the site, redeployed by pipelab).
- **Search**, **secrets** and **guidance** as before: `git grep` over served files by name; every answer filtered for
  secrets last, credential files never served; a repository's own guidance (all, none, or `own: [patterns]`), the
  operators' text and files, `from` another repository.
- **Released**: 0.2.0 on PyPI and `ghcr.io/alexeiveselov92/repo-reader-mcp:0.2.0` (public, amd64 + arm64). **The
  site**: https://rrm.pipelab.dev, with the new page `/running-in-a-container/`.

## How it was verified

- 282 tests on made-up repositories and hosts (real git, no network); ruff clean; CI green on `main` and on the tag.
- Every protection taken out in turn — 15 more this session (the `/health` bypass exactly, readiness at start, at the
  first round and never cleared, the log filter, groups not listed yet): its test failed each time.
- The image run as a deployment runs it: `--read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges`,
  mirroring this repository by https and reading a mounted made-up one — `503` → `200` in ~3 s, a restart over the kept
  volume ready at once, stopped in 0.7 s; the Python SDK's client and the MCP Inspector reading through it, four files
  equal to `git show`. Both platforms tried locally and by CI, the published image too.
- A fourth refuting review (a second agent): ~15 ways around the token through `/health` — none worked; 9 other
  findings, all closed (`dev/DECISIONS.md`).
- Not verified: a full sync over ssh in the container (needs an ssh server); ssh itself runs and reaches a host.

## Next step

**The deployment, in the company's own repository** (a session opened there, not here): its `deploy/` running
`ghcr.io/alexeiveselov92/repo-reader-mcp:0.2.0` behind its MCP gateway as an application-owned backend, `/health` as the
readiness probe, the gateway's key as `http.token_env`, the mirrors on a volume. What it needs that the server lacks
comes back here as general requirements with made-up examples — then milestone 6 is done.

## What the author needs to do

- For the deployment: a dedicated read-only GitHub token (fine-grained: Contents and Metadata, read) for the
  company's repositories.
- A new version: bump `version` in `pyproject.toml`, `uv lock`, a CHANGELOG line, push `main`, wait for every workflow
  to be green, then push the tag `v<version>` (it publishes PyPI and the image; `dev/DECISIONS.md`, 2026-10-25).

## Don't

- Don't write a real company, product, repository or path anywhere here — the repository is public.
- Don't add a tool without `read_only_hint=True`, `destructive_hint=False`, and its entry in `docs/reference/tools.md`.
- Don't add a page to `docs/` without listing it in `website/scripts/sync-docs.mjs` and the sidebar.
- Don't pass an agent's ref to git: resolve it to a commit id first; an agent's pattern goes after `-e` only.
- Don't give git a path pattern for what include / exclude decide — give it the served files by name.
- Don't match an agent's pattern again on hidden text: decide by the hidden spans of the line as written.
- Don't let any path but exactly `/health` past the bearer token, and don't let `/health` name or read anything.
- Don't turn readiness back off once set; don't use `/health` as a liveness probe in the guide's examples.
- Don't set `safe.directory = *` in the image; don't publish an image as `latest`.
- Don't add a protection without a test that fails when it is removed.
