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
- **Remote repositories are mirrored** (milestone 2): a bare partial clone (`--filter=blob:none`) in the server's own
  data folder — commits and trees of the whole history, and only the file contents a tool reads or the search index
  needs. A mirror is a local repository the server made, so every reading tool works on it unchanged.
- **Groups** (milestone 2): `github: owner/prefix-*` (and GitLab's groups) — resolved from the host's listing on every
  sync: a new repository joins, an archived one leaves; `skip` takes names or patterns out (a pattern catches more than
  wanted). Each member is named by its own repository name; the entry's settings (token, `include` / `exclude`,
  description, guidance) apply to all of them — written once for dozens of services. The pattern of the author's
  earlier platform and of a company workspace's sync scripts (`dev/RESEARCH.md`).
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

## Repositories' guidance for agents (planned — after milestone 1's tools)

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

- **What counts as guidance** (a list the configuration can change): `AGENTS.md` (the cross-vendor convention),
  `CLAUDE.md`, `GEMINI.md`, `.github/copilot-instructions.md`, `.claude/rules/**/*.md` (a rule's `paths:` frontmatter
  scopes it), `.cursor/rules/*.mdc` (`globs:`), `.claude/skills/*/SKILL.md` (name and description; the body on demand),
  and `AGENTS.md` / `CLAUDE.md` in subfolders (scoped to their folder).
- **Delivered like a client delivers its own**: the server's instructions say repositories carry guidance from their
  owners; the first answer about a repository in a session carries its guidance (the configuration's text first, then
  `from`, then the repository's own root files and unscoped rules, and a list of the scoped rules and skills); the first
  answer touching a scoped path carries that scope's guidance once; `read_guidance` gives all of it, or one skill.
- **Read from the default branch** of the repository (or of the `from` repository) — never from the ref an agent is
  reading: text presented to an agent as instructions is a way to steer it, and anyone who can push a branch could
  write one; the default branch is the reviewed one. A repository not trusted that far sets `own: false`.
- **It obeys `include` / `exclude`** like every other path; `--check` warns when a guidance file is outside them.
- **Sized**: guidance takes a capped share of an answer; the rest is one `read_guidance` away.

## Tools (all read-only)

| Tool | What |
|---|---|
| `list_repos` | the repositories, their default branch, the commit it is at, their branches and tags (milestone 1) |
| `list_refs` | branches and tags of one repository (milestone 1) |
| `read_file` | a file at a ref, as numbered lines, a window at a time (milestone 1) |
| `list_files` | a folder at a ref, or every file under it (milestone 1) |
| `log` | commits of a ref or a path, newest first; by author, message, since, until (milestone 1) |
| `show_commit` | one commit: message, author, files changed, its diff (capped) (milestone 1) |
| `diff` | between two refs, or since their merge base, for a path or the whole tree (capped) (milestone 1) |
| `blame` | who last changed each line of a file, at a ref, grouped by commit (milestone 1) |
| `read_guidance` | a repository's guidance for agents, or one skill (planned) |
| `search` | text or a regular expression across repositories (or some), with paths and line numbers |
| `grep` | `rg`, `find`, `ls`, `cat` in one repository at a ref — reading flags only |

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
  the server's back. In milestone 2 contents are fetched on purpose and in bulk by the sync, never by a reading
  command. Rename detection (which fetches on a partial clone) is off: `--no-renames`.
- **The environment can't redirect git**: every inherited `GIT_*` variable is dropped but the three naming which
  configuration files to read.
- **Secrets**: files named for credentials are never fetched; contents are scanned (gitleaks rules plus
  rules for passwords written as prose) and a found value is hidden before an agent sees the file (milestone 4; until
  then `exclude`, and the docs say so).
- **Tokens** travel in git's environment only — never a command line, a remote URL or a mirror's config;
  error messages are scrubbed of them.
- **Sizes**: every answer is capped (clients cut long answers — Claude Code near 25,000 tokens); a cut
  answer says so and how to narrow. Git's output is read up to a byte cap (4 MB; a file 10 MB) and the command
  stopped there; every parser drops a record the cap cut through, and the answer says it is partial.
- **What `exclude` doesn't hide**: commit messages, and — in the history of a whole branch — commits that changed only
  excluded paths. Open question for the author: list only commits that changed something served (messages stay free
  text either way).
- **Read-only toward the hosts**: GET-only APIs, `git fetch`; never a push.

## Transports and clients

stdio for one person's agent; Streamable HTTP for a shared server (a bearer token, or behind the
organisation's gateway). JSON-RPC ids may be strings or numbers. Checked with more than one client.

## Documentation, distribution and hosting

- **Documentation**: `docs/` is the single source of the public documentation. A site is built from it with Astro +
  Starlight (`website/`, the pattern of the author's detectkit: a `sync-docs` script imports `docs/` at build time,
  served by nginx from an image) at `repo-reader.pipelab.dev` (proposed).
- **Distribution**: the package on PyPI (`uvx repo-reader-mcp`); a container image on GHCR
  (`ghcr.io/alexeiveselov92/repo-reader-mcp`); the site's image beside it (`ghcr.io/alexeiveselov92/repo-reader-mcp-web`).
- **Hosting (the author's own)**: the author's server is run as code in `alexeiveselov92/pipelab` — Docker Compose
  behind Traefik; each service a compose entry with its Traefik host rule and TLS; secrets in GitHub, prefixed per
  service; a `deploy-<name>.yml` workflow that pulls and restarts a service on a `repository_dispatch` sent by this
  project's CI. The site is one such service; an instance of the server (for the author's own use, or a public demo
  over made-up data) is another — `/mcp` routed with no redirect, as the author's fluentkit and finkit do. Any other
  installation runs the same image its own way.

## Not in scope (for now)

Writing to repositories; issues, pull requests and reviews (the hosts' own MCP servers do that); a code
graph or embeddings (maybe later, as an optional way in); a web UI.
