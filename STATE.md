# Where we are

> Rewritten entirely at the end of every session by `/close`. Don't append. Under 100 lines.

**Updated:** 26 October 2026.

**Current milestone: 6, ready to deploy and proved by a real installation** (`dev/PLAN.md`).
- Its first half is done: the container image, `/health` and the guide's page, released as 0.2.0.
- Its second half, a company deploying it from its own repository, is in that company's hands.

**0.3.0 is released** (PyPI and the image). **0.3.1 is committed, being released**: push `main`, wait for every workflow
to go green, then push the tag `v0.3.1`.

## What 0.3.1 changes

Over HTTP, a GET of `/mcp` is answered `405` at once, with `Allow: POST` and a short JSON body: the server is stateless
and offers no stream. MCP's Streamable HTTP allows exactly two answers to that GET: open a `text/event-stream`, or
`405`.
- **Before:** the SDK, served stateless with JSON answers, answered `200` and held an empty event stream open until the
  client gave up. Measured on loopback: 8.0 s, by curl's `--max-time`, with or without SSE in `Accept`, token or not.
  A POST `initialize` took 1.5–3.5 ms. The published 0.3.0 image did the same.
- **Why it matters:** an MCP gateway in front of the server waits on that GET. It asked for `405`.
- **How:** `NoStream` (`src/repo_reader_mcp/server.py`), a small ASGI layer in front of the SDK's app, compares the path
  with trailing slashes stripped. It sits inside `BearerToken`: a GET without the token is still `401`, nothing else.
  The sibling server makes the same change, as `_NoStream`.
- **Checked:** `tests/test_http.py`, through a real uvicorn server, with a 3 s timeout, so without the layer the test
  fails rather than hangs. The layer removed: both cases failed (`200` after 3.0 s). `NoStream` put outside the token:
  the 401 test failed. The image's CI try (`.github/scripts/try-image.sh`) now checks the 405 too, on every image.

## What exists

- **Thirteen read-only tools** (`src/repo_reader_mcp/tools.py`, `about` in `server.py`):
  - **finding repositories and refs:** `list_repos`, `list_refs` (with `contains`);
  - **reading files:** `read_file`, `list_files`;
  - **history:** `log`, `show_commit`, `diff`, `blame`, `search_commits`;
  - **searching code:** `search` (across repositories), `grep` (one repository, any ref);
  - **the rest:** `read_guidance`, `about`.

  Every answer names the commit, is capped and links to the host's page.
- **From a ticket to the code (0.3.0):** `search_commits` finds commits by message across repositories, each saying
  how it reached the default branch. `list_refs(contains=…)` names the branches and tags holding a commit.
- **Refs (0.3.0)** are a name or an id, followed by `~N` / `^N` steps; the rest of git's revision syntax is refused.
- **Histories that hide commits** are judged whole, in growing batches, before anything is cut; read NUL-delimited.
- **Serving:** local, mirrored and grouped repositories; stdio and Streamable HTTP (stateless, JSON answers, no
  stream); a bearer token or a gateway; `/health`; the image on GHCR (amd64, arm64, per release, never `latest`).

## How it was verified

- **Tests:** 335 on made-up repositories (real git, no network), ruff clean, the site builds.
- **Protections:** every one fails its test when removed; 0.3.1's two (the 405, the token outermost) checked so.
- **Refuting reviews:** five so far; their findings are in `dev/DECISIONS.md`.

## Next step

1. **Release 0.3.1:** push `main`, wait for green, push the tag `v0.3.1`; check PyPI and the GHCR image `0.3.1`, then
   run the published image and see `GET /mcp` answer `405` at once while `POST` still answers.
2. **The deployment**, in the company's own repository: it moves to 0.3.1, which its gateway needs.
   - Whatever it needs that the server lacks comes back here as general requirements with made-up examples.
   - When it is deployed, milestone 6 is done.

## What the author needs to do

- A new version: bump `version` in `pyproject.toml`, `uv lock`, a CHANGELOG line; push `main`, wait for green, then
  push the tag `v<version>`.

## Don't

- Don't write a real company, product, repository or path anywhere here: the repository is public.
- Don't add a tool without `read_only_hint=True`, `destructive_hint=False` and its entry in
  `docs/reference/tools.md`.
- Don't pass an agent's ref to git. Check it (`check_ref`), look it up (`_revision`), and pass on the commit id.
- Don't cut a history before judging what is left out of it; don't count what is left out.
- Don't parse git's output by separators a message, a name or a path can hold: use NUL.
- Don't give git a path pattern for what include / exclude decide; give it the served files by name.
- Don't match an agent's pattern again on hidden text.
- Don't let any path but exactly `/health` past the bearer token; keep `NoStream` inside it.
- Don't publish an image as `latest`.
- Don't add a protection without a test that fails when it is removed.
