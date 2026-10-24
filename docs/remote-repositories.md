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

Every key is in the [configuration reference](reference/configuration.md). A company with many repositories names them
by a pattern instead — a [group](#groups).

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

## Groups

A group names many repositories at once — every repository of an owner whose name matches a pattern:

```yaml
repositories:
  - github: acme/shop-*                               # every repository of acme named shop-…
    token_env: GITHUB_TOKEN
    skip: [shop-sandbox, "acme/shop-*-legacy"]         # names or patterns left out
    description: One of the shop's services.
    exclude: ["**/fixtures/**", "*.pem"]               # the entry's settings apply to every repository of it

  - gitlab: acme/backend/**/svc-*                      # GitLab: a group's path, `**/` reaches into its subgroups
    host: git.example.com                              # a GitLab or GitHub of your own (default gitlab.com / github.com)
    token_env: GITLAB_TOKEN
```

**The host lists them on every sync.** Before each sync the server asks the host's API which repositories the owner
has: a repository created since joins (its mirror is made at that sync), an **archived** one leaves, and so does one
deleted, or one `skip` now names. Between two syncs the set stays as it was. The owner is a GitHub organisation or
user, or a GitLab group (only its own projects — not those shared with it from elsewhere) or user. A user's private
repositories are listed when the token is that user's own.

**Each repository is named by its own name** — `shop-api`, not `acme/shop-api` — and served with the entry's settings:
the token, `refs`, `include` / `exclude`, `listed`, guidance. Its description is the entry's `description` followed by
the one the host shows. `list_repos` says which group a repository came from:

```
## shop-api
One of the shop's services. — The shop's public API.
Mirrored from https://github.com/acme/shop-api.git (one of `github: acme/shop-*`), synced 2026-10-24 10:30 UTC.
```

**The pattern** follows the habits of `include`: `*` matches within a name, `?` one character; letters' case is
ignored, as hosts ignore it. For GitLab, the pattern is the last part of the path — `acme/backend/*` takes the
projects directly in `acme/backend` — and `**/` before it reaches into subgroups at any depth (`acme/backend/**` takes
them all). **`skip`** takes names (`shop-sandbox`) or patterns; an item with a `/` is matched against the full path
(`acme/shop-*-legacy`).

What a group leaves out, and why, `--check` and the log say:

```
  github: acme/shop-*  https://github.com
    the host lists 2 repositories it takes:
    shop-api  acme/shop-api  (mirror made)
    shop-web  acme/shop-web  (not mirrored yet)
    left out: acme/shop-old: archived
    left out: acme/shop-sandbox: skipped
```

- **A name already taken** — by a repository listed one by one, or by an earlier group's — keeps its first owner; the
  later one is left out and the log says so. So is a repository **listed one by one under another name** (the same
  address, however spelt): it is served once, with its own entry's settings. A repository listed one by one is how one member gets settings of its own:
  `skip` it in the group and list it by its `url`.
- **A name this server can't serve** (one starting with a dot, like `.github`) is left out.
- **A group's repository can't be a [guidance](reference/guidance.md) source** (`from`): a source is listed one by one,
  so it never comes and goes with a listing.

Answers about a mirrored repository carry a [link to the host's page](reference/tools.md#what-every-reading-tool-shares)
for what they show — known for GitHub, GitLab and Bitbucket and for a group's host; for a host of your own, name its
kind with `links: gitlab` (or `github`, `bitbucket`; `none` turns links off).

**When the host can't be reached** (or refuses the token), the group keeps the repositories it had and the log says
why; the next sync tries again. The last listing is kept in the mirrors folder, so a server that restarts serves the
group's repositories at once, before it asks the host.

**Addresses come from the configuration.** A repository's git address is built from the host and the path the
listing gives (`https://github.com/acme/shop-api.git`) — never taken from the listing itself — and a path with a `..`
in it, or characters a name can't have, is left out. The listing is read from the host's API only: a redirect is not
followed, and a next page that points anywhere else is refused — the token travels with those requests.

## Tokens

`token_env` names the environment variable that holds the token; the token itself is never written in the
configuration. Give the server a **read-only** token:

| Host | Token | `token_user` |
|---|---|---|
| GitHub | a fine-grained personal access token with *Contents: read* on the repositories, or a GitHub App's installation token | not needed |
| GitLab | a personal, group or project access token with `read_repository` | `oauth2` |
| Bitbucket Cloud | a repository access token with *Repositories: read* | `x-token-auth` |
| Any other git server over https | whatever it accepts as a password | the user it expects |

For a **group**, the token also lists the owner's repositories: on GitHub, a fine-grained token with access to the
organisation's repositories (*Metadata: read*, given with any access, and *Contents: read*); on GitLab, `read_api` as
well as `read_repository`. `token_user` defaults to `x-access-token` for a GitHub group and `oauth2` for a GitLab one.
A group of public repositories needs no token — GitHub then answers 60 listings an hour, plenty for a sync every 10
minutes.

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

- `<name>-<digest>.git` — the mirror; the digest is of its URL, `refs`, `include`, `exclude` and the token's variable,
  so a mirror holds what one configuration takes — another server sharing the folder, or this configuration changed,
  gets a mirror of its own;
- `<name>-<digest>.status.json` — when it last synced, the last error and the tags it doesn't keep, read by every
  server process sharing the folder;
- `<name>-<digest>.lock` — taken while a sync writes, so two server processes (two people's agents on one machine) take
  turns;
- `<github|gitlab>-<owner>-<digest>.members.json` — a group's last listing: its repositories, what it left out and why,
  when the host last listed it and the last error.

A mirror can be deleted at any time while the server is stopped; the next sync makes it again. A mirror no
configuration names any more (after `refs`, `include` or `exclude` changed, or a repository left its group) is left as
it was — delete it by hand.

## Checking and syncing by hand

```bash
repo-reader-mcp --config config.yaml --check   # also asks each host whether it answers and lists each group, keeping nothing
repo-reader-mcp --config config.yaml --sync    # lists every group and brings every mirror up to date once, exits
```

`--check` prints, for a remote repository, its mirror's folder and what the host has:

```
  shop-backend  https://github.com/acme/shop-backend.git
    mirror: /var/lib/repo-reader-mcp/shop-backend-3f2a9c1d0b4e.git (made)
    host: reachable: 12 branches and 40 tags, of which it keeps 3 and 40
```

`--sync` exits with code 1 when any group couldn't be listed or any mirror failed — usable from a scheduler of your
own, with `every_minutes: 0`.

## Fixed limits

A command that reaches the host may run for 30 minutes (a first fetch of a long history takes a while); up to four
mirrors sync at once. One request to a host's API may take 30 seconds; a group lists up to 20,000 repositories. The
server logs each listing and each sync to its standard error.
