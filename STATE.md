# Where we are

> Rewritten entirely at the end of every session by `/close`. Don't append. Under 100 lines.

**Updated:** 24 October 2026.

**Current milestone: 2 — remote repositories** (`dev/PLAN.md`). Milestone 1 (local repositories, read-only) is done.
Order changed by the author: remote repositories now come before the docs site (milestone 3).

## What exists

- **Configuration** (`src/repo_reader_mcp/config.py`): YAML, every problem named at once (`repositories[1] (shop) →
  path: …`), `--check` lists what is served and its guidance and warns about guidance kept out. Remote keys (`url`,
  `token_env`, `refs`, `sync`) are refused with "not supported yet".
- **Nine read-only tools** over local repositories (checkout or bare), at any ref: `list_repos`, `list_refs`,
  `read_file`, `list_files`, `log`, `show_commit`, `diff` (with `since_fork`), `blame`, `read_guidance`; plus `about`.
  Plain-text answers naming the commit, capped (`limits.answer_characters`, 40,000), saying how to continue.
- **include / exclude** with `.gitignore`'s habits (`src/repo_reader_mcp/paths.py`); an excluded path is never listed,
  diffed, read or blamed; narrowing to one is refused by the path alone; a history leaves out commits that changed only
  what is not served.
- **Guidance for agents** (`src/repo_reader_mcp/guidance.py`): `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, copilot
  instructions, `.claude/rules`, `.cursor/rules`, skills — on the default branch only; plus configuration text/files,
  `from` a folder of another repository, `listed: false`, `own: false`. Every answer about a repository with guidance
  says so in one line; a short scoped rule rides with answers about its paths.
- **Safety** (`src/repo_reader_mcp/git.py`, `docs/reference/safety.md`): a fixed set of git commands, refs resolved to
  commit ids first, `--no-ext-diff --no-textconv --no-show-signature --no-ignore-revs-file`, `protocol.allow=never`,
  inherited `GIT_*` dropped, every git output capped at 4 MB.
- **The guide** (`docs/`): getting started; reference — tools, configuration, guidance, safety.

## How it was verified

- 124 tests on made-up repositories the tests build (real git, no network); ruff clean.
- Every protection (25) taken out in turn: its test failed each time (a script in the session's scratch, not kept).
- A refuting review by a second agent: found `blame.ignoreRevsFile` reading any file on the server's disk (closed),
  uncapped git output (capped), the history telling excluded activity (filtered). Two findings of my own while
  building: a branch can be named `--output=<file>` (refs resolved first); textconv runs in a bare repository from the
  commit's `.gitattributes` (the trap test is bare).
- Real Claude Code over stdio (`claude -p --mcp-config … --strict-mcp-config`, only the server's tools): 9 questions
  about the made-up shop answered correctly; with guidance, it called `read_guidance` by itself in every conversation
  and followed rules it couldn't have guessed (a product name, a commit format, a scoped "ask finance" rule, a line from
  a `from` source).

## Waiting for the author

- **Confirm the guidance delivery** (`dev/DECISIONS.md`, "Guidance is announced by every answer"): MCP keeps no session
  between requests (revision 2026-07-28), so "the first answer in a session carries it" can't be built; every answer
  says it in one line instead.

## Next step — milestone 2

1. Mirrors: bare partial clones (`--filter=blob:none`) in the server's data folder from any git URL; a token by
   variable name, in git's environment only; a sync at start and on a schedule that is the only thing allowed to fetch
   (reading commands keep `protocol.allow=never`); force-pushes followed; contents fetched on purpose, never by a
   reading command.
2. Groups: `github: owner/prefix-*` (and GitLab groups) resolved from the host on every sync — new repositories join,
   archived leave; `skip` (names or patterns); the entry's settings and guidance apply to every member.
3. Streamable HTTP with a bearer token; a second MCP client checked (not Claude).
4. Tests against made-up "remote" repositories served over `file://` (no network); a real check against a public host.

## What the author needs to do

- Nothing blocks the start of milestone 2. For a real check of groups against GitHub, a read-only token in an
  environment variable may be asked for later in the session.

## Don't

- Don't write a real company, product, repository or path anywhere here — the repository is public.
- Don't add a tool without `read_only_hint=True`, `destructive_hint=False`, and its entry in `docs/reference/tools.md`.
- Don't pass an agent's ref to git: resolve it to a commit id first (`Repository.resolve`).
- Don't add a git command or a flag that reads the working tree, runs a program or reaches a host from a reading call.
- Don't add a protection without a test that fails when it is removed.
