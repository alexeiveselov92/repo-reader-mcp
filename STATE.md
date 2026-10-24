# Where we are

> Rewritten entirely at the end of every session by `/close`. Don't append. Under 100 lines.

**Updated:** 24 October 2026 (mid-session: the author asked to keep working in the same session).

**Current milestone: 4 — search and safety** (`dev/PLAN.md`). Milestones 1 (local repositories), 2 (remote
repositories, groups, HTTP, links) and 3 (the docs site, live at https://repo-reader.pipelab.dev) are done.

## What exists

- **Eleven read-only tools** at any ref (`src/repo_reader_mcp/tools.py`): `list_repos`, `list_refs`, `read_file`,
  `list_files`, `log`, `show_commit`, `diff`, `blame`, `search` (across repositories, default branches), `grep` (one
  repository, any ref, context lines), `read_guidance`; plus `about`. Answers name the commit, are capped, and carry a
  link to the host's page (GitHub, GitLab, Bitbucket, or `links:`).
- **Repositories**: local (`path`); mirrored (`url`: bare partial clones in the cache folder, a token by variable name,
  synced at start and every `mirrors.every_minutes`, contents of served paths only, older contents fetched on purpose);
  groups (`github: owner/pattern`, `gitlab: group/**/pattern`, `skip`, `host`, `forks`) listed by the host's API before
  every sync, the last listing kept on disk; the set served is a catalog (`catalog.py`), replaced whole, one set per
  tool call.
- **Transports**: stdio; Streamable HTTP (`--http [HOST:]PORT`, stateless, JSON) behind `http.token_env` or
  `http.behind_gateway`; a non-loopback address with neither is refused.
- **Search**: `git grep` given the served files by name (never a path include / exclude keep out), the pattern after
  `-e`; no index — 0.2–0.4 s over 18 real repositories.
- **The guide** (`docs/`) and **the site** (`website/`, Astro + Starlight, redeployed by pipelab on every push to main;
  a page of `docs/` the site doesn't list fails the build and `tests/test_docs.py`).

## How it was verified

- 248 tests on made-up repositories and made-up hosts (real git, no network); ruff clean; CI green (lint, tests, the
  site's build).
- Every protection taken out in turn — 33 (mirrors), 28 (groups, HTTP), 4 (search): its test failed each time (scripts
  in the session's scratch, not kept).
- Two refuting reviews by a second agent: 11 findings on mirrors, 10 on groups and HTTP — all closed with tests.
- Real clients: Claude Code over stdio and HTTP and the MCP Inspector (TypeScript SDK) over both, against a mirrored
  public repository and an 18-repository public GitHub group; a cross-repository question answered with `search`.

## Next step — milestone 4, the rest

1. **The secret scan**: values that look like secrets (keys, tokens, private key blocks, passwords in assignments and
   in prose) hidden in everything an answer shows from a repository — files, blame, diffs, search hits, messages;
   the answer says how many it hid.
2. **Files named for credentials never served or fetched** (`.env`, `*.pem`, `*.key`, `id_rsa`, …), with a
   per-repository way to serve them on purpose.
3. A refuting review of the whole safety; every protection with a test that fails when it is removed.

## What the author needs to do

- Nothing blocks the work. All decisions asked of the author are settled (`dev/DECISIONS.md`).

## Don't

- Don't write a real company, product, repository or path anywhere here — the repository is public.
- Don't add a tool without `read_only_hint=True`, `destructive_hint=False`, and its entry in `docs/reference/tools.md`.
- Don't add a page to `docs/` without listing it in `website/scripts/sync-docs.mjs` and the sidebar.
- Don't pass an agent's ref to git: resolve it to a commit id first; an agent's pattern goes after `-e` only.
- Don't give git a path pattern for what include / exclude decide — give it the served files by name.
- Don't add a protection without a test that fails when it is removed.
