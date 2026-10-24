# Remote repositories

repo-reader-mcp reads a repository on a code host — GitHub, GitLab, Bitbucket, any git server — by keeping a
**mirror** of it on the machine it runs on. People's agents never clone anything: they ask the server, and the server
reads its mirror.

```yaml
repositories:
  - url: https://github.com/acme/shop-backend.git     # named shop-backend, from its url
    token_env: GITHUB_TOKEN                           # the variable holding a read-only token
    refs: [main, "release/*", "v*"]                   # the branches and tags kept; the default branch always
    exclude: ["**/fixtures/**", "*.pem"]

mirrors:
  folder: /var/lib/repo-reader-mcp                    # where mirrors live
  every_minutes: 10                                   # how often each one is brought up to date
```

Every key is in the [configuration reference](reference/configuration.md).

## What a mirror holds

A mirror is a bare **partial clone**:

- **the whole history** — every commit, and every folder listing — of the branches and tags it keeps;
- **the contents of the files it serves** at the tips of those branches and tags — nothing outside `include` /
  `exclude`;
- the contents of **older versions** of served files, once an agent has read them.

So a mirror is a fraction of a full clone's size, and the contents of a path kept out by `exclude` (or not taken by
`include`) never reach the server's disk at all.

## How it stays fresh

The **sync** runs when the server starts, and then every `mirrors.every_minutes` (10 by default; `0` syncs at start
only). For each repository it:

1. asks the host what branches and tags it has;
2. moves the mirror's branches and tags to match — a force-pushed branch is followed, a deleted one is dropped, a branch
   or tag that `refs` doesn't name is not kept;
3. fetches the contents of the served files at the tips that moved.

The first sync makes the mirror; until it is done, the repository answers that it is being mirrored — ask again in a
minute. A mirror appears complete or not at all: a first sync that fails leaves nothing behind, and the server tries
again at the next one. When a later sync fails, the server goes on serving the mirror as it was, and `list_repos` says
when it last synced and why the last sync failed:

```
## shop-backend
Mirrored from https://github.com/acme/shop-backend.git, synced 2026-10-24 10:30 UTC.
Default branch: main @ 14a4c0422ae3 (2026-10-24) — Fix the cart total for empty carts
```

A sync never disturbs a reader: it adds commits and moves branch pointers, and an agent reading a commit finishes on
it. Every answer names the commit it read.

## Reading an older commit

The reading tools take any commit the mirror holds — the whole history of every kept branch and tag. When a tool needs
the contents of a file at an older commit (a file as it was, a diff, a blame), the server fetches those contents from
the host first, **on purpose and for served paths only**, and then reads. The git commands that read never reach the
host themselves.

A commit that is on no kept branch or tag (a branch `refs` leaves out, a pull request's head) is not in the mirror;
the answer says so. A tag of a folder or of a file's contents, rather than of a commit, is not kept.

**Blame and renamed files.** Blame follows a file through renames. Where a file was renamed *with changes* (or simply
appeared beside files deleted in the same commit), git finds where it came from by comparing it with those deleted
files — so the mirror fetches them too, and blame goes on, as long as they are all served. Where one of them isn't,
blame stops at that commit and says so: lines shown at it are as old as it, or older; `log` and `show_commit` tell the
rest.

## Tokens

`token_env` names the environment variable that holds the token; the token itself is never written in the
configuration. Give the server a **read-only** token:

| Host | Token | `token_user` |
|---|---|---|
| GitHub | a fine-grained personal access token with *Contents: read* on the repositories, or a GitHub App's installation token | not needed |
| GitLab | a personal, group or project access token with `read_repository` | `oauth2` |
| Bitbucket Cloud | a repository access token with *Repositories: read* | `x-token-auth` |
| Any other git server over https | whatever it accepts as a password | the user it expects |

The token is sent as an `Authorization` header to the URL's host only, over https, given to git through its
environment — never on a command line (which any user of the machine can read), in a URL, in the mirror's files or in
an error. With a token, the server follows **no redirect**: git would carry the header to wherever a redirect points.
A host that redirects (a renamed repository, a URL without `.git`) fails the sync with a message saying so — give `url`
as the address it redirects to. The server account's credential helpers and password programs are not used with a
token.

Without `token_env`, git uses what the server's account has: for `ssh://` and `git@host:path` URLs, its ssh keys and
`~/.ssh/config`; for https, any credential helper it has set up. Nothing ever asks for a password interactively.

## The mirrors folder

`mirrors.folder` — by default `~/.cache/repo-reader-mcp` (or `$XDG_CACHE_HOME/repo-reader-mcp`) — holds, per
repository:

- `<name>-<digest>.git` — the mirror; the digest is of its URL, `refs`, `include` and `exclude`, so a mirror holds what
  one configuration takes — another server sharing the folder, or this configuration changed, gets a mirror of its own;
- `<name>-<digest>.status.json` — when it last synced, the last error and the tags it doesn't keep, read by every
  server process sharing the folder;
- `<name>-<digest>.lock` — taken while a sync writes, so two server processes (two people's agents on one machine) take
  turns.

A mirror can be deleted at any time while the server is stopped; the next sync makes it again. A mirror no
configuration names any more (after `refs`, `include` or `exclude` changed) is left as it was — delete it by hand.

## Checking and syncing by hand

```bash
repo-reader-mcp --config config.yaml --check   # also asks each host whether it answers, keeping nothing
repo-reader-mcp --config config.yaml --sync    # brings every mirror up to date once, says what changed, exits
```

`--check` prints, for a remote repository, its mirror's folder and what the host has:

```
  shop-backend  https://github.com/acme/shop-backend.git
    mirror: /var/lib/repo-reader-mcp/shop-backend-3f2a9c1d0b4e.git (made)
    host: reachable: 12 branches and 40 tags, of which it keeps 3 and 40
```

`--sync` exits with code 1 when any mirror failed — usable from a scheduler of your own, with `every_minutes: 0`.

## Fixed limits

A command that reaches the host may run for 30 minutes (a first fetch of a long history takes a while); up to four
mirrors sync at once. The server logs each sync to its standard error.
