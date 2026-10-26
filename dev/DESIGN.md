# Design — repo-reader-mcp

The working design. A decision that changes it goes to [DECISIONS.md](DECISIONS.md) first.

## What it is

One MCP server. It knows a set of **repositories** from a YAML configuration and offers read-only tools
over them. It never writes to a repository, never runs a program a person names, never reaches a host it
wasn't told about.

## Repositories

```yaml
repositories:
  - name: shop-backend            # how agents and tools name it
    url: https://github.com/acme/shop-backend.git
    token_env: GITHUB_TOKEN       # the variable holding a read-only token, never the token
    refs: [main, "release/*"]     # branches and tags kept fresh; any commit still readable on demand
    include: ["src/**", "docs/**"]
    exclude: ["**/fixtures/**"]
  - github: acme/shop-*           # a group: every repository whose name matches, resolved from the host
    token_env: GITHUB_TOKEN
    skip: [acme/shop-sandbox, "acme/shop-*-legacy"]   # names or patterns left out of the group
    description: The shop's backend services
    exclude: ["vendor/**"]        # an entry's settings apply to every member
  - name: local-notes
    path: /srv/notes              # a repository already on disk, read as it is
```

- **Local repositories** (`path`, built in milestone 1): a checkout or a bare repository, read through its git
  directory. Relative paths are taken from the configuration file's folder.
- **Remote repositories are mirrored** (milestone 2, built 2026-10-24 — `src/repo_reader_mcp/mirror.py`): a bare
  partial clone (`--filter=blob:none`) in `mirrors.folder` (default `~/.cache/repo-reader-mcp`), named
  `<name>-<digest of the URL>.git` — commits and trees of the whole history of the kept refs, and the contents of
  served paths only. A mirror is a local repository the server made, so every reading tool works on it unchanged.
  - **The sync** (`Mirror.sync`, at start and every `mirrors.every_minutes`, four mirrors at once): `ls-remote`; fetch
    the refs that moved by explicit refspecs on stdin (`+` follows force-pushes, `--atomic`, `--no-tags`,
    `--recurse-submodules=no`); delete the refs gone or no longer kept (`update-ref --stdin`); point HEAD at the host's
    default branch (a host whose HEAD is a commit: the branch at it); fetch the served contents at the tips that moved
    (and the default branch's), listing files from a commit's root. Tags of a tree or a blob are dropped once fetched
    and remembered in the status, so they aren't fetched again. A first sync builds
    in `<name>-<digest>.new` and renames it into place when complete — a mirror exists whole or not at all. One writer
    per mirror: a thread lock and `flock` on `<name>-<digest>.lock`. The outcome is written to
    `<name>-<digest>.status.json` so every server process sharing the folder can tell it (`list_repos`).
  - **Contents on purpose** (`Mirror.ensure`): before a command that reads contents (`cat-file`, `numstat`, `diff -p`,
    `blame`), the repository asks the mirror for the (object, path) pairs it needs; the mirror drops paths outside
    include / exclude, finds the missing ones with `rev-list --objects --no-walk --ignore-missing --missing=print
    --stdin` (which never fetches), and fetches exactly those (`fetch --stdin origin <ids>`, negotiation `noop`). A diff
    counts lines of served files only, by path, so git never wants an excluded file's contents; a served file replaced
    by a folder of unserved files is left out of the pathspecs (git takes a path as a folder too), and a patch keeps
    only the sections of the files asked for. Blame takes the file's history with `log --follow -M100% --raw` (exact
    renames, found by id, need no contents; gitlinks left out); where git still wants contents — the files deleted in
    the commit where the file appeared, to follow a rename with changes — the mirror fetches those when all are served,
    asks git where the file came from (`log -1 --follow`), and goes on from there (up to 8 hops). Where one isn't
    served, blame reruns as `<that commit>..<ref>` and says it stopped there.
  - **Tokens** by variable name, given to git through `GIT_CONFIG_COUNT`: `credential.helper=` (reset),
    `core.askPass=` (off), `http.<the repository's URL>.followRedirects=false` (the closest match, which the machine's
    configuration can't override), `http.<scheme://host/>.extraHeader: Authorization: Basic …`; https only (plain http
    to the loopback only). No redirect with a
    token: git keeps an extra header chosen at the start for every request, wherever a redirect sends them (found by a
    test, 2026-10-24). Without a token, git uses the server account's setup (ssh keys, a credential helper).
- **Groups** (milestone 2, built 2026-10-24 — `src/repo_reader_mcp/hosts.py`, `catalog.py`): `github: owner/pattern`,
  `gitlab: group/path/pattern` (`**/` reaches into subgroups), `host` for a GitHub Enterprise or GitLab of one's own,
  `skip` (names, or patterns matched against the full path when they hold a `/`). Before every sync the host's API
  lists the owner's repositories (GitHub: the organisation's, else the user's — the user's own token lists their
  private ones; GitLab: the group's own projects, `with_shared=false`, else the user's): the pattern takes them, `skip`
  and archived ones leave, a path with `.`/`..` parts or a name the server can't serve is left out. A member is named by
  its repository's name and served with the entry's settings (token, `refs`, `include` / `exclude`, `listed`,
  guidance); its description is the entry's, then the host's. The **catalog** (`Catalog`) is the set served: the
  repositories listed one by one, then each group's members; it is rebuilt after each listing and replaced whole, so a
  tool reads one consistent set; a member keeps its `Repository` while its settings are unchanged. A name taken by a
  repository listed one by one, or by an earlier group's member, keeps its first owner (the later one is left out,
  logged). The last listing is kept as `<kind>-<owner>-<digest>.members.json` in the mirrors folder: a restart serves
  the members at once, and a host that can't be reached leaves the members as they were. Listing: urllib, `GET` only,
  no redirect followed, a next page (`Link`) must stay on the API's origin and path, the token as a bearer header (not
  passed on a redirect even if one were followed), errors scrubbed of it; git addresses built from the host and the
  listed path — never the listing's `clone_url`. A group's repository can't be a guidance source (`from` names
  repositories listed one by one). The pattern of the author's earlier platform and of a company workspace's sync
  scripts (`dev/RESEARCH.md`).
- **Links to the host's pages** (milestone 2, built 2026-10-24 — `src/repo_reader_mcp/links.py`): GitHub, GitLab and
  Bitbucket forms for a file at a commit with its lines, a folder, a commit, a comparison (not Bitbucket's, which takes
  branch names); known from the host's name (github.com, gitlab.com, bitbucket.org), a group's kind, or `links:` for a
  host of one's own (`none` turns them off). Built from the repository's address and commit ids — never an agent's text;
  a link names the commit, so it shows what the answer showed after the branch moves.
- **`include` is an allow-list**: a repository that holds something that must never be read (exports,
  tickets) names what it takes; a folder added later stays out. `exclude` drops from what is taken. Patterns follow
  `.gitignore`'s habits (a pattern with no `/` matches at any depth; a pattern naming a folder takes what is in it), so
  an `exclude` written to keep something out keeps it out wherever it is.
- **Refs**: the default branch always; others by name or pattern; any commit by its id when asked.
- A pass on a schedule (and at start) fetches each mirror; a force-pushed branch is followed.

## How reading works — and why many people can read different branches at once

The server **never checks anything out**. A checkout lays one branch's files into a working folder — one folder, one
branch, and two readers would collide. Inside a git repository every branch, tag and commit is stored at once (a branch
is a pointer to a commit), and the server reads from there: "the file `src/app.py` in commit `a1b2…`". So:

- **Only what is committed is read.** A checkout's uncommitted changes and untracked files are never seen.
- **Many readers, many refs, at the same time**: each tool call is a few short git commands reading one commit; nothing
  is shared between calls. One copy per repository, however many people and branches.
- **A sync never disturbs a reader**: a fetch adds commits and moves branch pointers; a reader already holding a commit
  id finishes on it. Every answer names the commit it read, so an agent knows exactly which version it saw.
- **A ref is resolved once**, to a commit id, at the start of a call; every later command of the call gets the id.

## Repositories' guidance for agents (milestone 1 — built 2026-10-24)

A repository often carries rules written for agents (`AGENTS.md`, `CLAUDE.md`, `.claude/rules/`, skills). An agent
reading it through this server is not inside its folder, so its own client loads none of it. The server delivers it,
as instructions — not as one more file.

```yaml
guidance:                         # for every repository on this server
  text: |
    Answer about data in terms of the business, not table names.
repositories:
  - name: acme-rules              # a repository that holds guidance for others
    path: /srv/acme-rules
    listed: false                 # a source of guidance only; agents don't see it
  - name: acme-dbt
    path: /srv/acme-dbt
    guidance:
      text: |                     # written in the configuration
        Revenue is stored in cents. Staging models are internal — answer from marts.
      files: [/srv/notes/dbt.md]  # files on the server's disk
      from:                       # from another configured repository: its AGENTS.md, rules/, skills/
        - repo: acme-rules        # as if they lived in acme-dbt (a rule's `paths:` read against acme-dbt)
          path: dbt/
      own: true                   # the repository's own guidance files (default); false to ignore them
```

- **What counts as guidance** (a fixed list for now; the configuration may change it later): `AGENTS.md` (the
  cross-vendor convention),
  `CLAUDE.md`, `GEMINI.md`, `.github/copilot-instructions.md`, `.claude/rules/**/*.md` (a rule's `paths:` frontmatter
  scopes it), `.cursor/rules/*.mdc` (`globs:`), `.claude/skills/*/SKILL.md` (name and description; the body on demand),
  and `AGENTS.md` / `CLAUDE.md` in subfolders (scoped to their folder).
- **Delivered without a session.** MCP keeps no session between requests (protocol revision 2026-07-28: each request
  is its own exchange — found while building this, 2026-10-24), so the server can't know what an agent read in its
  conversation. Every answer about a repository with guidance starts with one line saying so and naming
  `read_guidance(repo=…)`; an answer about a path a scoped rule covers carries the rule when the scope's guidance is
  short (≤ 1,500 characters), else names it; `read_guidance` gives all of it (the configuration's text first, then
  `from`, then the repository's own files; scoped rules with their scope; skills named), or one piece. Guidance takes
  at most half of an answer. Seen working: real Claude Code called `read_guidance` on its own in every conversation and
  followed rules it could not have guessed — a product name, a commit format, a scoped "ask finance" rule, a line from
  a `from` source.
- **Read from the default branch** of the repository (or of the `from` repository) — never from the ref an agent is
  reading: text presented to an agent as instructions is a way to steer it, and anyone who can push a branch could
  write one; the default branch is the reviewed one. A repository not trusted that far sets `own: false`.
- **It obeys `include` / `exclude`** like every other path; `--check` warns when a guidance file is outside them.
- **Sized**: guidance takes a capped share of an answer; the rest is one `read_guidance` away.

## Tools (all read-only)

| Tool | What |
|---|---|
| `list_repos` | the repositories, their default branch, the commit it is at, their branches and tags (milestone 1) |
| `list_refs` | branches and tags of one repository (milestone 1); with `contains`, those holding a commit, when it reached the default branch, the earliest tag that has it (0.3.0) |
| `read_file` | a file at a ref, as numbered lines, a window at a time (milestone 1) |
| `list_files` | a folder at a ref, or every file under it (milestone 1) |
| `log` | commits of a ref or a path, newest first; by author, message, since, until (milestone 1) |
| `search_commits` | commits across repositories by message, on every branch and tag, each with how it reached the default branch — made on its first-parent line, or the merge that brought it (`log --ancestry-path` against `log --first-parent`), or not in it (0.3.0) |
| `show_commit` | one commit: message, author, files changed, its diff (capped) (milestone 1) |
| `diff` | between two refs, or since their merge base, for a path or the whole tree (capped) (milestone 1) |
| `blame` | who last changed each line of a file, at a ref, grouped by commit (milestone 1) |
| `read_guidance` | a repository's guidance for agents, or one skill (planned) |
| `search` | text or a regular expression across repositories (or some), on each default branch, with paths and line numbers — `git grep` per repository, eight at once, given the served files by name (built 2026-10-24) |
| `grep` | text or a regular expression in one repository at any ref, with lines of context or files only — `git grep` the same way (built 2026-10-24) |

Every answer names the repository, the ref and the commit it was read at, and a link to the host's page
when the host has pages.

## Safety

The public account is `docs/reference/safety.md`; each protection has a test that fails when it is removed.

- **Nothing is a shell.** Commands come from a fixed set (`src/repo_reader_mcp/git.py`), arguments are a list; for
  `grep` (milestone 4) each checked against an allow-list of that command's flags; never one that runs a program
  (`rg --pre`, `find -exec`), writes, follows a link out of the repository or reads a config. Paths stay inside the
  repository: they are looked up in a commit's tree, never on the disk.
- **An agent's text never reaches git as anything but a ref to resolve.** A ref is refused when it starts with `-` or
  holds whitespace; `rev-parse --verify --end-of-options <ref>^{commit}` resolves it; every later command gets the id.
  A branch *can* be named `--output=/some/file` (anyone who can push can make one), and `git diff` given that name
  writes the file — found and tested 2026-10-24.
- **No program or file a repository names**: `--no-ext-diff --no-textconv` on `diff`, `--no-textconv
  --no-ignore-revs-file` on `blame` (`blame.ignoreRevsFile` reads any file on the server's disk and git echoes its
  lines in an error — found by the refuting review, 2026-10-24), `--no-show-signature` on `log`. Textconv matters most on a bare repository (a mirror): git takes `.gitattributes`
  from the commit there, so a driver the attributes name is in force (a checkout read through its git directory has no
  working files to take them from) — found 2026-10-24; the test's trap repository is bare for that reason.
- **No accidental downloads.** `protocol.allow=never` on every reading command: a partial clone never fetches behind
  the server's back. Contents are fetched on purpose — by the sync, and by `Mirror.ensure` before a read — never by a
  reading command, and only for served paths (checked in `ensure` itself, whoever calls it). Rename detection (which
  fetches on a partial clone) is off: `--no-renames`, except blame's own following and `log --follow -M100%`, which
  find renames by object id and read no contents.
- **Nothing from a commit's own files**: `attr.tree` is the empty tree and `mailmap.blob` empty on every call. A bare
  repository (a mirror) reads `.gitattributes` and `.mailmap` from HEAD — files the repository's authors write, which a
  mirror may not hold (found 2026-10-24: a diff failed on a mirror whose `include` left `.gitattributes` out; the
  refuting review found every tool failing when it left `.mailmap` out). No hooks: `core.hooksPath` is the null
  device (the sync's ref updates would run a `reference-transaction` hook of the machine's, with the token in its
  environment).
- **Each protocol refused by name**: `protocol.allow=never` is a default that a `protocol.file.allow=always` in the
  machine's configuration overrides, so every known protocol gets its own `never`, and reading runs with
  `GIT_NO_LAZY_FETCH=1` (git 2.44+, and patched older ones). Two layers, each tested alone.
- **A mirror per configuration**: its folder's digest covers the URL, `refs`, `include` and `exclude`.
- **The sync's own command set** (`git.maintain`): `init`, `config`, `ls-remote`, `fetch`, `update-ref`,
  `symbolic-ref`, `for-each-ref`, `ls-tree`, `rev-list`; only `ls-remote` and `fetch` reach a host, by the URL's own
  protocol alone (`protocol.allow=never` plus `protocol.<it>.allow=always`) — an `insteadOf` can't switch it. URLs
  with credentials and remote helpers (`ext::`) are refused in the configuration.
- **The environment can't redirect git**: every inherited `GIT_*` variable is dropped but the three naming which
  configuration files to read.
- **Secrets** (built 2026-10-24 — `src/repo_reader_mcp/secrets.py`): files named for credentials are left out by the
  matcher (`paths.CREDENTIAL_FILES`; `serve_credential_files: true` per entry), so never served nor fetched; every
  answer and every error passes `tools.shown` last — providers' token formats, URL passwords, key material, values of
  settings named for secrets (references and placeholders left), passwords in prose — each replaced by
  `[hidden: <what>]`, the count said. A private key's block is hidden whole where the file is whole (`read_file`,
  `blame`; `search` / `grep` find the blocks with a second `git grep` over the files they hit). A hit found only inside
  a hidden value is dropped (search, grep, and log / search_commits by message — `--extended-regexp`, re-read by
  Python), so a guessed secret can't be confirmed; a history by message — or of a repository served in part — streams
  the ids of the matches (`Repository.matching`, `git.stream`: no limit of bytes) only as far as `visible` judges them,
  in batches growing from 200 to 6,400 (`clean` reads each message whole, NUL-delimited, in the order asked; `serving`
  reads each commit's files), within a minute for the whole call, then reads the details of those shown — so the
  commits read depend on those kept, never on those left out, and a commit left out never shifts what is shown or the
  "more" note (0.3.0; 0.2.0 paged first and cut first). Every history git prints is read with NUL between
  fields: a subject or a path holding git's other separators can't forge a line.
- **Refs** (0.3.0): a name looked up among `refs/tags`, `refs/heads`, `refs/remotes` (git's order) or an id among
  commits and tags (`rev-parse --disambiguate`, then `cat-file --batch-check`) whose commit a branch, a tag or HEAD has
  (`for-each-ref --contains`, `merge-base`), then `~N` / `^N` steps; a whole id is never looked up as a name, and a start
  of one that is also a name is refused; `check_ref` refuses the rest of git's syntax before any lookup — `^{/…}` and
  `:/…` were an oracle on commit messages, a character at a time. `GIT_NO_REPLACE_OBJECTS=1` on every call.
- **Tokens** travel in git's environment only — never a command line, a remote URL, a mirror's files or its status;
  error messages are scrubbed of them (the token, `user:token`, its base64). With a token, no redirect is followed and
  the account's credential helpers are off.
- **Sizes**: every answer is capped (clients cut long answers — Claude Code near 25,000 tokens); a cut
  answer says so and how to narrow. Git's output is read up to a byte cap (4 MB; a file 10 MB) and the command
  stopped there; every parser drops a record the cap cut through, and the answer says it is partial.
- **What `exclude` doesn't hide**: commit messages (free text). A history leaves out commits that changed only excluded
  paths (the author, 2026-10-24): `log --name-only --diff-merges=first-parent`, kept when any changed path is served
  or nothing changed, paged after that choice.
- **Read-only toward the hosts**: GET-only APIs, `git fetch`; never a push.

## Transports and clients

stdio for one person's agent; Streamable HTTP for a shared server (built 2026-10-24 — `--http [HOST:]PORT`, the SDK's
`streamable_http_app` at `/mcp`, **stateless** and with **JSON answers**: nothing kept between requests, so restarts and
copies behind a load balancer are invisible to clients, and gateways pass plain JSON through). **No stream** (0.3.1):
a GET of `/mcp` (trailing slashes aside) is answered `405`, `Allow: POST`, by `NoStream` in front of the SDK's app —
the SDK, stateless, answered it `200` and held an empty `text/event-stream` open until the client gave up, which a
gateway waits on; the SDK's DELETE was already `405`. `NoStream` sits inside the bearer token. Who may call: a bearer
token (`http.token_env`, an ASGI middleware comparing in constant time, `401` otherwise) or `http.behind_gateway: true`;
on a non-loopback address one of them is required. On loopback the SDK's DNS-rebinding protection answers only
`127.0.0.1` / `localhost` / `[::1]` as the Host. JSON-RPC ids may be strings or numbers. Checked with Claude Code and
the MCP Inspector (the TypeScript SDK's client), over stdio and HTTP.

**`/health`** (built 2026-10-24, milestone 6): a custom route the bearer middleware lets through for exactly that path
of an HTTP request, nothing else. `200 {"status": "ready"}` once `Catalog.ready` is set — at start when every group
has a kept listing and every mirror is made (a restart over a kept folder), or when the first sync round is over
(whatever it achieved); `503 {"status": "syncing"}` before. Never cleared: a host failing later, or a member joining
and not mirrored yet, takes nothing from what is served (a check computed at each probe flapped — the fourth review).
It names nothing and reads nothing; a GET or HEAD of it is left out of uvicorn's access log (`QuietProbes`). For a
readiness probe — a liveness probe on it would restart a server in its first, minutes-long sync. A group no host has
listed yet is named by `list_repos` and by the unknown-repository error, with the host's error (`Catalog.unlisted`):
a server ready after a failed first listing doesn't pass for one with nothing configured.

**The container image** (built 2026-10-24, milestone 6; the root `Dockerfile`, `Dockerfile.dockerignore` an allow-list
of what it is built from): `python:3.12-slim-trixie`, git 2.47 (asserted ≥ 2.44 at build: `GIT_NO_LAZY_FETCH`), an ssh
client, Perl's modules and git's manual purged (perl-base stays); user `reader` 10001 named in `/etc/passwd` (ssh refuses to run for a uid with no
name); `HOME=/home/reader`; `XDG_CACHE_HOME=/data`, so the default `mirrors.folder` is `/data/repo-reader-mcp` with no
configuration of its own; `REPO_READER_MCP_CONFIG=/config/config.yaml`; `CMD --http 0.0.0.0:8000` (the configuration
must then say a token or a gateway). Runs on a read-only root with `/tmp` (git's stderr goes through temporary files)
and `/data` writable. `safe.directory` is not relaxed in the image: a mounted local repository of another owner is
refused at start with a message naming the two ways out (run as its owner, or `safe.directory` in a git configuration
named by `GIT_CONFIG_GLOBAL`). `.github/workflows/image.yml` builds it for each platform on every push and pull
request and tries each (`.github/scripts/try-image.sh`: read-only, mirroring this repository by https, ready, `401`
without the token, a file read with it; arm64 under emulation); for a tag `v*` only it publishes both from the same
cached layers — tagged with the version and `sha-…`, never `latest` — and tries the published image again.

## Documentation, distribution and hosting

- **Documentation**: `docs/` is the single source of the public documentation. The site is built from it with Astro +
  Starlight (`website/`, built 2026-10-24 on the pattern of the author's detectkit: `scripts/sync-docs.mjs` imports
  `docs/` and the changelog at build time — titles from each page's H1, links between pages rewritten to routes, links
  to other files of the repository to GitHub, an "edit" link per page; a page of `docs/` it doesn't list stops the
  build, and `tests/test_docs.py` checks the same; the landing page is `website/src/pages/index.astro` — a standalone page with its own styles, on the pattern of
  detectkit's: a hero with a real exchange, sections showing what the tools actually print, made-up data only), served by nginx
  from an image (`website/Dockerfile`, pushed to GHCR by `.github/workflows/website.yml`, which then sends
  `repository_dispatch: repo-reader-mcp-updated` to pipelab) at `rrm.pipelab.dev`.
- **Distribution**: the package on PyPI (`uvx repo-reader-mcp`); a container image on GHCR
  (`ghcr.io/alexeiveselov92/repo-reader-mcp`); the site's image beside it (`ghcr.io/alexeiveselov92/repo-reader-mcp-web`).
- **Hosting (the author's own)**: the author's server is run as code in `alexeiveselov92/pipelab` — Docker Compose
  behind Traefik; each service a compose entry with its Traefik host rule and TLS; secrets in GitHub, prefixed per
  service; a `deploy-<name>.yml` workflow that pulls and restarts a service on a `repository_dispatch` sent by this
  project's CI. The docs site is the only one — pipelab runs no instance of the server. An installation (a company's,
  in its own repositories) runs the published image its own way, typically behind its MCP gateway.

## Not in scope (for now)

Writing to repositories; issues, pull requests and reviews (the hosts' own MCP servers do that); a code
graph or embeddings (maybe later, as an optional way in); a web UI.
