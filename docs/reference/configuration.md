# Configuration

One YAML file tells repo-reader-mcp which repositories to serve and how large an answer may be. The server reads it at
start; a wrong entry stops the server before it serves anything, naming the entry and the key.

```bash
repo-reader-mcp --config /etc/repo-reader/config.yaml                    # serve over stdio
repo-reader-mcp --config /etc/repo-reader/config.yaml --http 0.0.0.0:8000  # serve over Streamable HTTP at /mcp
repo-reader-mcp --config /etc/repo-reader/config.yaml --check            # check the file, list what it serves, exit
repo-reader-mcp --config /etc/repo-reader/config.yaml --sync             # list groups, sync every mirror once, exit
REPO_READER_MCP_CONFIG=/etc/repo-reader/config.yaml repo-reader-mcp
```

## An example

```yaml
repositories:
  - name: shop-backend
    path: /srv/code/shop-backend
    description: The shop's backend — orders, payments, the public API.
    exclude: ["**/fixtures/**", "*.pem"]

  - url: https://github.com/acme/shop-frontend.git   # mirrored; named shop-frontend
    token_env: GITHUB_TOKEN
    refs: [main, "release/*"]

  - github: acme/billing-*            # a group: every repository of acme named billing-…
    token_env: GITHUB_TOKEN
    skip: [billing-sandbox]

  - name: handbook
    path: ../handbook                 # relative to this file's folder
    include: ["docs/**", "README.md"]

mirrors:
  folder: /var/lib/repo-reader-mcp
  every_minutes: 10

limits:
  answer_characters: 40000

http:
  token_env: REPO_READER_MCP_TOKEN    # with --http: the bearer token clients send
```

## `repositories`

A list; at least one. Each entry is one repository — a local one (`path`) or a remote one (`url`) — or a group of
remote ones (`github:` or `gitlab:`); exactly one of the four.

| Key | | |
|---|---|---|
| `name` | required for `path` | How agents and tools name it. Up to 100 letters, digits, `.`, `_`, `-`, starting with a letter or digit; unique. For a remote repository it defaults to the last part of its URL, without `.git`. |
| `path` | | A repository on the server's disk — its top folder: a checkout (with its `.git` inside) or a bare repository. `~` is expanded; a relative path is taken from the configuration file's folder. A folder *inside* a repository is refused — the whole repository above it would be served. |
| `url` | | A repository on a code host, [mirrored](../remote-repositories.md): `https://…`, `http://…`, `ssh://…`, `git@host:path`, `git://…` or `file://…`. A URL can't carry credentials (`https://user:token@…` is refused — name the token's variable in `token_env`), a query or a fragment; remote helpers (`ext::…`) are refused. Changing `url`, `refs`, `include`, `exclude` or `token_env` makes a new mirror. |
| `github` | | A [group](../remote-repositories.md#groups): `owner/pattern` — every repository of a GitHub organisation or user whose name matches (`acme/shop-*`), listed by the host on every sync; archived ones are left out. Each is mirrored and named by its own name; the entry's other keys apply to every one of them. Takes no `name`. |
| `gitlab` | | A GitLab [group](../remote-repositories.md#groups): `group/path/pattern` — the projects of a group (or user) whose name matches; `**/` before the pattern reaches into subgroups (`acme/backend/**/svc-*`). |
| `host` | | With `github` / `gitlab`: a GitHub Enterprise or GitLab of your own — its name (`git.example.com`, https) or address (`https://example.com/gitlab`). Default `github.com` / `gitlab.com`. |
| `forks` | `false` | With `github` / `gitlab`: `true` takes the owner's forks too; otherwise they are left out. |
| `skip` | | With `github` / `gitlab`: repositories the pattern takes but the group leaves out — names (`shop-sandbox`) or patterns; an item with a `/` is matched against the full path (`acme/shop-*-legacy`) and must be the owner's. |
| `token_env` | | With an https `url` or a group (plain http only to this machine): the name of the environment variable that holds a read-only token — never the token. The server won't start when the variable is not set. Without it, git uses the server account's own setup (ssh keys, a credential helper), and a group lists public repositories only. [Which token for which host](../remote-repositories.md#tokens). |
| `token_user` | | The user name sent with the token. Default `x-access-token` (GitHub, and a GitHub group); `oauth2` for GitLab (a GitLab group's default), `x-token-auth` for Bitbucket Cloud. |
| `links` | | With `url` or a group: the kind of the host's web pages, for [links](tools.md#what-every-reading-tool-shares) in answers — `github`, `gitlab`, `bitbucket`, or `none` (no links). Default: known for github.com, gitlab.com, bitbucket.org and for a group's host; for any other host, none until it is named. |
| `refs` | | With `url` or a group: the branches and tags a mirror keeps, by name or pattern (`main`, `release/*`, `v*` — `*` matches any characters, `/` included). The default branch is always kept. Not given: every branch and tag. |
| `description` | | A sentence for agents: what this repository is. Shown by `list_repos`. |
| `listed` | | `false` keeps it from agents — out of `list_repos` and every tool — as a source of [guidance](guidance.md) for other repositories only. Default `true`. |
| `guidance` | | [Guidance for agents](guidance.md) about this repository: `text`, `files`, `from` (folders of other repositories listed one by one — a group's repository can't be a source), `own` (its own `AGENTS.md`, rules and skills: `true`, the default; `false`; or patterns of the ones to take). |
| `serve_credential_files` | `false` | `true` serves the files named for credentials (`.env`, `*.pem`, `*.key`, `id_rsa`, … — [the list](safety.md#files-named-for-credentials-are-never-served)), which are otherwise left out — and, on a mirror, never fetched. Their secrets are still hidden. Changing it makes a new mirror. |
| `include` | | Patterns of the paths served. When given, only these are served — a folder added to the repository later stays out until a pattern takes it. Not given: everything. |
| `exclude` | | Patterns of paths never served, even inside `include`. |

**Only what is committed is served.** The server reads commits, never a checkout's working files: changes not
committed, and files never added (a local `.env`), are not seen. A checkout's own branch is its default branch; a
mirror's is the host's.

### Patterns

`include` and `exclude` follow `.gitignore`'s habits, so a pattern written to keep something out keeps it out wherever
it is:

| Pattern | Matches |
|---|---|
| `src/**` | everything under `src/` |
| `src` | the same: a pattern that names a folder takes everything in it |
| `*.pem` | a pattern with no `/` matches at any depth: `prod.pem`, `keys/deep/prod.pem` |
| `/*.pem` | a leading `/` anchors it to the root: `prod.pem` only |
| `**/fixtures/**` | everything under any `fixtures/` folder |
| `docs/*.md` | `.md` files directly in `docs/`, not in its subfolders |
| `secrets` | everything under every `secrets/` folder, at any depth |

`*` matches within one folder name, `?` one character, `**` any number of folders. `[` and `]` are taken literally.

A path is served when `include` (if given) matches it and `exclude` doesn't.

## `guidance`

[Guidance for agents](guidance.md) for every repository on the server: `text`, and `files` on the server's disk (read at
start; relative paths from this file's folder).

## `mirrors`

Where remote repositories are mirrored, and how often ([how mirrors work](../remote-repositories.md)).

| Key | Default | |
|---|---|---|
| `folder` | `~/.cache/repo-reader-mcp` | The folder mirrors live in (`$XDG_CACHE_HOME/repo-reader-mcp` when that is set). `~` is expanded; a relative path is taken from the configuration file's folder. Made at the first sync. |
| `every_minutes` | 10 | How often each mirror is brought up to date, from 0 to 1440. The server syncs at start, then this often; `0` syncs at start only. |

## `http`

Who may call the server when it serves over Streamable HTTP (`--http [HOST:]PORT`; [running it for a
team](../serving-over-http.md)). Not used over stdio.

| Key | Default | |
|---|---|---|
| `token_env` | | The name of the environment variable holding the bearer token every request must carry (`Authorization: Bearer …`) — never the token. The server won't start when the variable is not set. |
| `behind_gateway` | `false` | `true`: no token here — a gateway in front of the server checks who calls. |

On an address other than this machine's own (`127.0.0.1`, `::1`, `localhost`), one of the two is required: the server
won't start open to anyone who reaches its port.

## `limits`

| Key | Default | |
|---|---|---|
| `answer_characters` | 40,000 | The most characters one answer may have, from 2,000 to 1,000,000. Clients cut long answers themselves (Claude Code near 25,000 tokens, roughly 100,000 characters of code); a cut answer from this server says what it left out and how to get it. |

Fixed limits, not configured: a file over 10 MB is not read; a line over 2,000 characters is cut; blame works on up to
5,000 lines a call; one git command's output is read up to 4 MB (a larger tree, history or list of changes is answered
in part, saying so) and the command may run for 30 seconds.

## When the file is wrong

Every problem is named at once, with where it is:

```
repo-reader-mcp: the configuration config.yaml has 3 problems:
  - repositories[0] (shop-backend) → path: /srv/code/shop-backnd is not a folder
  - repositories[1] (shop-frontend) → token_env: the variable GITHUB_TOKEN is not set in the server's environment
  - repositories[2] (handbook) → colour: an unknown key
```

The server exits with code 2 and serves nothing.
