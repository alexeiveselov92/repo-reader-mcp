# Tools

Every tool repo-reader-mcp offers to an agent. All are read-only: each says so to the client (`read_only_hint`, never
`destructive_hint`). A tool appears here in the same commit that adds it — a test fails otherwise.

## What every reading tool shares

- **`repo`** — a repository's name, as `list_repos` shows it.
- **`ref`** — any branch, tag or commit id: `main`, `release/2.1`, `v1.2.0`, `a1b2c3d`, `main~3`, `origin/main`.
  Without it, the repository's default branch (for a local repository: the branch its checkout is on).
- **Paths** are written from the repository's root: `src/app.py`, `docs`. A leading or trailing `/` is ignored; `..`
  and `.` are refused.
- **Only what is committed is read.** Files changed but not committed in a checkout, and files never added, are not
  seen — every tool reads the commit a ref points at.
- **Every answer names where it read**: the repository, the ref and the commit (`main @ a1b2c3d4e5f6 (2026-03-01)`).
- **Every answer is capped** at `limits.answer_characters` (40,000 by default — [configuration](configuration.md)). A
  cut answer ends with a note in brackets saying what was left out and how to get it: the `start_line` to continue
  from, the `skip` to page on, or the `path` to narrow to.
- **Paths outside the repository's `include` / `exclude` are never shown** — not listed, not in a diff, not read.
  Asked for by name, the answer is that the path is outside what this server serves.
- **Guidance comes first.** An answer about a repository that carries [guidance for agents](guidance.md) starts with a
  line saying so; an answer about a path a short scoped rule covers carries the rule, between `=== Guidance … ===` and
  `=== End of guidance — the answer follows ===`. Guidance takes at most half of an answer.

## `about`

What this server is, its version and status. Call it to check the connection. Takes nothing; answers its name, version,
status, `read_only: true` and how many repositories it serves.

## `list_repos`

The repositories this server reads. Takes nothing. For each: its name, its description (from the configuration), its
default branch with the commit it is at, the date and the subject of that commit, how many branches and tags it has,
whether only part of it is served, and whether it carries [guidance for agents](guidance.md). Repositories configured
with `listed: false` are not shown.

```
## shop
A made-up shop.
Default branch: main @ 14a4c0422ae3 (2026-03-01) — Add the catalog and assets; drop the legacy config
2 branches, 2 tags — list_refs lists them
```

## `list_refs`

Branches and tags of one repository, newest first: each one's name, the commit it points at (for an annotated tag, the
commit the tag is on), the date and the subject. `*` marks the default branch.

| Input | |
|---|---|
| `repo` | the repository |
| `kind` | `all` (default), `branches` (with remote-tracking branches such as `origin/main`), or `tags` |
| `pattern` | only names matching a glob: `release/*`, `v1.*` |

## `read_file`

A file at any ref, as numbered lines.

| Input | |
|---|---|
| `repo`, `ref` | as above |
| `path` | the file |
| `start_line` | the first line to show (default 1) |
| `max_lines` | at most this many lines (default: as many as fit in the answer) |

The first line of the answer names the file, the ref, the commit and the window: `lines 1–850 of 3001`. A file longer
than the answer is cut where the answer is full, with the `start_line` that continues it. A line longer than 2,000
characters (minified code) is cut, saying how many characters were left out.

Not shown as text: a **binary file** (its size is given), a **symbolic link** (its target is given; it is not followed
— read the target by its own path), a **submodule** (the commit it pins is given). A file over 10 MB is not read.
A folder is refused with a pointer to `list_files`.

## `list_files`

A folder at any ref.

| Input | |
|---|---|
| `repo`, `ref` | as above |
| `path` | the folder (default: the root) |
| `recursive` | every file under the folder, at any depth, instead of its direct content |

Without `recursive`: its subfolders (ending in `/`) and then its files, each with its full path from the root. With
`recursive`: every file under it. Links are marked `(link)`, submodules `(submodule)`. A folder holding nothing this
server serves is answered as a folder that isn't there. Sizes are not shown.

## `log`

The history of a ref — of the whole repository or of one path — newest first: each commit's id, date (when it was
committed), author and subject.

| Input | |
|---|---|
| `repo`, `ref` | as above — `ref` is where the history starts from |
| `path` | only commits that changed this file or folder |
| `author` | only commits whose author's name or email matches (a regular expression, any case) |
| `message` | only commits whose message matches (a regular expression, any case) |
| `since`, `until` | only commits after / before a date: `2026-01-31`, `2 weeks ago` |
| `max_count` | at most this many commits (default 30, up to 500) |
| `skip` | skip this many first — to page on; a cut answer gives the next `skip` |

A file's history stops where the file was renamed: renames are not followed. When the repository is served only in
part (`include` / `exclude`), the history lists only commits that changed something served — or nothing at all — and
says so; `skip` counts the commits shown. Messages are shown as their authors wrote them.

## `show_commit`

One commit.

| Input | |
|---|---|
| `repo` | the repository |
| `commit` | a commit id, or any ref (the commit it points at) |
| `path` | only the changes under this file or folder |
| `files_only` | only the list of changed files, without the diff |

The answer: the commit's id, author and date, who committed it and when (when that differs), its parents, the whole
message; the files it changed — `A` added, `M` modified, `D` deleted, `T` type changed — with lines added and removed;
then the diff. A merge is shown against its first parent (what the merge brought into the branch). The first commit of
a repository is shown as adding everything it holds. A rename shows as a deletion and an addition. A diff longer than
the answer is cut — narrow it with `path`.

## `diff`

The difference between two refs, as files changed and a diff.

| Input | |
|---|---|
| `repo` | the repository |
| `base` | the ref to compare from |
| `head` | the ref to compare to (default: the default branch) |
| `path` | only the changes under this file or folder |
| `since_fork` | compare from where `head` forked off `base` (their merge base): only what `head` changed — what a pull request would show. Without it, the two refs are compared as they are |
| `files_only` | only the list of changed files, without the diff |

The answer names both refs with their commits (and the merge base with `since_fork`), then the files and the diff as in
`show_commit`.

## `blame`

Who last changed each line of a file at a ref, and in which commit.

| Input | |
|---|---|
| `repo`, `ref` | as above |
| `path` | the file |
| `start_line`, `max_lines` | the window, as in `read_file` |

Lines are grouped under the commit that last changed them — its id, date, author and subject — so the reason for a line
is one `show_commit` away:

```
80f39763c22b 2026-02-15 Grace Hopper — Fix the cart total for empty carts
12	        if not self.items:
13	            return 0
```

Binary files and links are refused.

## `read_guidance`

The [guidance](guidance.md) a repository carries for agents — written by its owners (`AGENTS.md`, `CLAUDE.md`, rules,
skills) and by the people who run the server — read on its default branch.

| Input | |
|---|---|
| `repo` | the repository |
| `name` | one piece, by the name the guidance gives it: a file (`AGENTS.md`, `.claude/rules/pricing.md`, `acme-rules:shop/AGENTS.md`) or a skill (`refund-flow`) |

Without `name`: everything in force — for the whole repository, and for some paths (each with its scope) — then the
pieces read when they fit the task (skills), named with the call that reads each. With `name`: that piece in full. A
repository with no guidance says so.
