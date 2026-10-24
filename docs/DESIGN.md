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
  - name: local-notes
    path: /srv/notes              # a local checkout, read as it is
```

- **Remote repositories are mirrored**: a partial clone (`--filter=blob:none`) — commits and trees of the
  history, and only the file contents a tool reads or the search index needs.
- **`include` is an allow-list**: a repository that holds something that must never be read (exports,
  tickets) names what it takes; a folder added later stays out. `exclude` drops from what is taken.
- **Refs**: the default branch always; others by name or pattern; any commit by its id when asked.
- A pass on a schedule (and at start) fetches each mirror; a force-pushed branch is followed.

## Tools (all read-only)

| Tool | What |
|---|---|
| `list_repos` | the repositories, their default branch, the commit each ref is at, how fresh |
| `list_refs` | branches and tags of one repository |
| `read_file` | a file at a ref, as numbered lines, a window at a time |
| `list_files` | a folder at a ref |
| `search` | text or a regular expression across repositories (or some), with paths and line numbers |
| `grep` | `rg`, `find`, `ls`, `cat` in one repository at a ref — reading flags only |
| `log` | commits of a repository or a path, newest first; by author, since, until |
| `show_commit` | one commit: message, author, files changed, its diff (capped) |
| `diff` | between two refs, for a path or the whole tree (capped) |
| `blame` | who last changed each line of a file, at a ref |

Every answer names the repository, the ref and the commit it was read at, and a link to the host's page
when the host has pages.

## Safety

- **Nothing is a shell.** Commands come from a fixed set, arguments are a list, each checked against an
  allow-list of that command's flags; never one that runs a program (`rg --pre`, `find -exec`), writes,
  follows a link out of the repository or reads a config. Paths stay inside the repository.
- **No accidental downloads.** A partial mirror fetches missing contents for some git commands
  (`cat-file` on a missing object, a diff, rename detection): reading goes through commands over commits
  and trees, contents are fetched on purpose and in bulk.
- **Secrets**: files named for credentials are never fetched; contents are scanned (gitleaks rules plus
  rules for passwords written as prose) and a found value is hidden before an agent sees the file.
- **Tokens** travel in git's environment only — never a command line, a remote URL or a mirror's config;
  error messages are scrubbed of them.
- **Sizes**: every answer is capped (clients cut long answers — Claude Code near 25,000 tokens); a cut
  answer says so and how to narrow.
- **Read-only toward the hosts**: GET-only APIs, `git fetch`; never a push.

## Transports and clients

stdio for one person's agent; Streamable HTTP for a shared server (a bearer token, or behind the
organisation's gateway). JSON-RPC ids may be strings or numbers. Checked with more than one client.

## Not in scope (for now)

Writing to repositories; issues, pull requests and reviews (the hosts' own MCP servers do that); a code
graph or embeddings (maybe later, as an optional way in); a web UI.
