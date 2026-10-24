# Plan

Measured in sessions — one sitting of the author's, from half an hour to a few hours. Each milestone ends
with something visible: a real agent answering through the server.

## Milestone 0. Groundwork — ✅ 2026-10-24

- [x] The repository, its license (Apache-2.0), README, design, decisions, research.
- [x] The session flow: `CLAUDE.md`, `/start`, `/close`, `STATE.md`, rules.
- [x] A running skeleton: the server over stdio with one tool, its test through the SDK's in-process client,
      lint, CI.

## Milestone 1. Local repositories, read-only — ✅ 2026-10-24

- [x] The configuration file (YAML) and its check: a wrong entry stops the server, naming it. (2026-10-24)
- [x] `list_repos`, `list_refs`, `read_file`, `list_files` at any ref of a local repository. (2026-10-24)
- [x] `log`, `show_commit`, `diff`, `blame` — sized answers, the commit named in each. (2026-10-24)
- [x] Tests on made-up repositories built by the tests themselves (real git, no network); every protection with a test
      that fails when it is removed (checked by taking each out). (2026-10-24)
- [x] Real Claude Code over stdio answers questions about a test repository. (2026-10-24)
- [x] Repositories' guidance for agents (`dev/DESIGN.md`): the repository's own `AGENTS.md` / `CLAUDE.md` / rules /
      skills, text and files from the configuration, a folder of another repository (`from`), `listed: false`; every
      answer says a repository has it, a short scoped rule rides with answers about its paths; `read_guidance`;
      `--check` warns about guidance outside `include`. Seen working: Claude Code following rules it could not have
      guessed from the code. (2026-10-24)

## Milestone 2. Remote repositories — ✅ 2026-10-24

- [x] Mirrors (2026-10-24): partial clones from any git URL, a token by variable name, `refs` kept fresh on a schedule,
      force-pushes followed; `include` / `exclude`; nothing fetched outside them (counted from the mirror).
- [x] Groups (2026-10-24): `github: owner/prefix-*` (and GitLab's groups) resolved from the host on every sync — new repositories
      join, archived ones leave; `skip` (names or patterns); the entry's settings and guidance apply to every member.
- [x] Hosts (2026-10-24): GitHub, GitLab, any git server — links to the host's pages where it has them.
- [x] Streamable HTTP with a bearer token; a second MCP client checked (not Claude) (2026-10-24: the MCP Inspector).

## Milestone 3. The docs site — ✅ 2026-10-24

- [x] `website/` (2026-10-24) — Astro + Starlight built from `docs/`, the author's detectkit pattern (`../detectkit/website`: the
      `sync-docs` script importing `docs/`, the nginx Dockerfile, the `website.yml` workflow pushing the image to GHCR and
      sending `repository_dispatch` to pipelab).
- [x] In pipelab (`../pipelab`, under its own rules; 2026-10-24): the site at `repo-reader.pipelab.dev` — a compose service
      behind Traefik and its `deploy-*.yml`, as detectkit's site is served.
- [x] The guide as it stands after milestone 2 published there (2026-10-24, https://repo-reader.pipelab.dev); from now on every milestone's pages go live with it.

## Milestone 4. Search and safety — ✅ 2026-10-24

- [x] `search` across repositories, `grep` in one at any ref (2026-10-24: `git grep` over the served files, no index —
      measured 0.2–0.4 s over 18 repositories; an index waits until numbers ask for one).
- [x] The secret scan before serving; files named for credentials never fetched (2026-10-24).
- [x] A refuting review of the safety (a second reader whose job is to break it); every protection with a
      test that fails when it is removed (2026-10-24: 11 findings, all closed).

## Milestone 5. The author's server instance — 1 session

- [ ] In pipelab: an instance of the server (its image from GHCR, `/mcp` routed with no redirect, a token or the
      organisation's gateway in front), its `deploy-*.yml`, secrets prefixed in GitHub — for the author's own use and a
      public demo over made-up data.

## Milestone 6. Release — 1 session

- [ ] Published on PyPI (`uvx repo-reader-mcp`), a container image, docs for agents and for people who
      run it; a versioned release.

## Later

A code graph as an optional way in; per-person access when served to a team (or left to a gateway);
pull requests and issues stay with the hosts' own servers.
