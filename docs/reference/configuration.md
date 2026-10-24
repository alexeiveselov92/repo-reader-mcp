# Configuration

One YAML file tells repo-reader-mcp which repositories to serve and how large an answer may be. The server reads it at
start; a wrong entry stops the server before it serves anything, naming the entry and the key.

```bash
repo-reader-mcp --config /etc/repo-reader/config.yaml          # serve over stdio
repo-reader-mcp --config /etc/repo-reader/config.yaml --check  # check the file, list what it serves, exit
REPO_READER_MCP_CONFIG=/etc/repo-reader/config.yaml repo-reader-mcp
```

## An example

```yaml
repositories:
  - name: shop-backend
    path: /srv/code/shop-backend
    description: The shop's backend — orders, payments, the public API.
    exclude: ["**/fixtures/**", "*.pem"]

  - name: handbook
    path: ../handbook                 # relative to this file's folder
    include: ["docs/**", "README.md"]

limits:
  answer_characters: 40000
```

## `repositories`

A list; at least one. Each entry is one repository.

| Key | | |
|---|---|---|
| `name` | required | How agents and tools name it. Up to 100 letters, digits, `.`, `_`, `-`, starting with a letter or digit; unique. |
| `path` | required | The repository's top folder: a checkout (with its `.git` inside) or a bare repository. `~` is expanded; a relative path is taken from the configuration file's folder. A folder *inside* a repository is refused — the whole repository above it would be served. |
| `description` | | A sentence for agents: what this repository is. Shown by `list_repos`. |
| `include` | | Patterns of the paths served. When given, only these are served — a folder added to the repository later stays out until a pattern takes it. Not given: everything. |
| `exclude` | | Patterns of paths never served, even inside `include`. |

**Only what is committed is served.** The server reads commits, never a checkout's working files: changes not
committed, and files never added (a local `.env`), are not seen. A checkout's own branch is its default branch.

Remote repositories (`url`, a token by name, `refs`, a sync schedule) are planned and not read yet: an entry with them
is refused with a message saying so.

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
repo-reader-mcp: the configuration config.yaml has 2 problems:
  - repositories[0] (shop-backend) → path: /srv/code/shop-backnd is not a folder
  - repositories[1] (handbook) → colour: an unknown key
```

The server exits with code 2 and serves nothing.
