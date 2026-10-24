# Plan

Measured in sessions — one sitting of the author's, from half an hour to a few hours. Each milestone ends
with something visible: a real agent answering through the server.

## Milestone 0. Groundwork — ✅ 2026-10-24

- [x] The repository, its license (Apache-2.0), README, design, decisions, research.
- [x] The session flow: `CLAUDE.md`, `/start`, `/close`, `STATE.md`, rules.
- [x] A running skeleton: the server over stdio with one tool, its test through the SDK's in-process client,
      lint, CI.

## Milestone 1. One local repository, read-only — 1–2 sessions

- [ ] The configuration file (YAML) and its check: a wrong entry stops the server, naming it.
- [ ] `list_repos`, `list_refs`, `read_file`, `list_files` at any ref of a local repository.
- [ ] `log`, `show_commit`, `diff`, `blame` — sized answers, the commit named in each.
- [ ] Tests on made-up repositories built by the tests themselves (real git, no network).
- [ ] Real Claude Code over stdio answers questions about a test repository.

## Milestone 2. The docs site — 1 session

- [ ] `website/` — Astro + Starlight built from `docs/`, the author's detectkit pattern (`../detectkit/website`: the
      `sync-docs` script importing `docs/`, the nginx Dockerfile, the `website.yml` workflow pushing the image to GHCR and
      sending `repository_dispatch` to pipelab).
- [ ] In pipelab (`../pipelab`, under its own rules): the site at `repo-reader.pipelab.dev` — a compose service
      behind Traefik and its `deploy-*.yml`, as detectkit's site is served.
- [ ] The guide as it stands after milestone 1 published there; from now on every milestone's pages go live with it.

## Milestone 3. Remote repositories — 2 sessions

- [ ] Mirrors: partial clones from any git URL, a token by variable name, `refs` kept fresh on a schedule,
      force-pushes followed; `include` / `exclude`; nothing fetched outside them (counted from the mirror).
- [ ] Hosts: GitHub, GitLab, any git server — links to the host's pages where it has them.
- [ ] Streamable HTTP with a bearer token; a second MCP client checked (not Claude).

## Milestone 4. Search and safety — 2 sessions

- [ ] `search` across repositories (an index), `grep` with allow-listed commands.
- [ ] The secret scan before serving; files named for credentials never fetched.
- [ ] A refuting review of the safety (a second reader whose job is to break it); every protection with a
      test that fails when it is removed.

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
