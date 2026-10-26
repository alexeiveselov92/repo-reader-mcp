# Where we are

> Rewritten entirely at the end of every session by `/close`. Don't append. Under 100 lines.

**Updated:** 26 October 2026.

**Current milestone: 6, ready to deploy and proved by a real installation** (`dev/PLAN.md`).
- Its first half is done: the container image, `/health` and the guide's page, released as **0.2.0**.
- Its second half, a company deploying it from its own repository, is now in that company's hands.

**0.3.0 is built and committed, not yet released.** Push `main`, wait for green CI, then push the tag `v0.3.0`. It
answers a question that installation asked: from a ticket to the code.

## What exists

- **Fourteen read-only tools** (`src/repo_reader_mcp/tools.py`):
  - **finding repositories and refs:** `list_repos`, `list_refs` (with `contains` in 0.3.0);
  - **reading files:** `read_file`, `list_files`;
  - **history:** `log`, `show_commit`, `diff`, `blame`, `search_commits` (0.3.0);
  - **searching code:** `search` (across repositories), `grep` (one repository, any ref);
  - **the rest:** `read_guidance`, `about`.

  Every answer names the commit, is capped and links to the host's page.
- **`search_commits`** finds commits by their message across repositories, on every branch, tag and HEAD (up to 10
  per repository). Each one says how it reached the default branch:
  - **made on it:** on the branch's first-parent line; the date is the commit's own;
  - **merged in a given commit:** with the merge's date;
  - **not in it.**

  The landing is worked out only for the commits the answer has room for.
- **`list_refs(contains=…)`** shows the branches and tags that hold a commit, how it reached the default branch, and
  the earliest tag that has it.
- **Refs (0.3.0)** are a name or an id, followed by `~N` / `^N` steps.
  - A name is looked up among `refs/tags`, `refs/heads` and `refs/remotes`.
  - An id is accepted only for a commit or tag whose commit some branch, tag or HEAD contains.
  - A whole id is always an id. The start of an id that is also a branch name is refused.
  - The rest of git's revision syntax is refused.
  - Replace refs are ignored.
- **Histories that hide commits.** A history by message, or of a repository served in part, streams the matching ids
  and judges them in batches growing from 200 to 6,400, only as far as needed, within a minute per call: `clean` (the
  message read whole), then `serving` (the files changed), then `details`. Every history is read NUL-delimited.
- **Unchanged since 0.2.0:** repositories (local, mirrored, groups), stdio and Streamable HTTP, secrets and guidance,
  `/health`, the image, CI.

## How it was verified

- **Tests:** 332 on made-up repositories (real git, no network), ruff clean, the site builds.
- **Protections:** each one added in this session was removed in turn, and its test failed every time (20). The two
  ref guards, the grammar and the lookup, each have their own test.
- **Refuting reviews:** a fifth one, run twice by a second agent with made-up repositories.
  - **First round:** 3 holes that 0.2.0 already had, plus the new code's.
    - `main^{/text}` read a token out of a commit message in 252 calls.
    - The message check could be slipped past.
    - A history was cut before it was judged.
  - **Second round:** all of those held, and it broke the fixes four ways:
    - an id shadowed by a branch with the same name;
    - a commit dated far in the future;
    - the 64 MB refusal used as an oracle;
    - ids that no ref reaches.

  All are closed or documented, in `dev/DECISIONS.md` (2026-10-26).
- **On a real installation's mirrors** (in-process MCP client): one ticket across 86 repositories in 0.7–0.9 s,
  `contains` in 0.3 s, a broad pattern in 3.7 s; a squash shows "made on it", a merged pull request its merge.

## Next step

1. **Release 0.3.0:** push `main`, wait for every workflow to go green, then push the tag `v0.3.0`.
2. **The deployment**, in the company's own repository: it should run 0.3.0, not 0.2.0, which has the ref hole.
   - Whatever it needs that the server lacks comes back here as general requirements with made-up examples.
   - When it is deployed, milestone 6 is done.

## What the author needs to do

- Say whether to release 0.3.0.
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
- Don't let any path but exactly `/health` past the bearer token.
- Don't publish an image as `latest`.
- Don't add a protection without a test that fails when it is removed.
