# Guidance for agents

A repository often carries rules written for agents: `AGENTS.md`, `CLAUDE.md`, `.claude/rules/`, skills. An agent
that reads the repository through repo-reader-mcp is not inside its folder, so its own client loads none of them. The
server delivers them — as guidance to follow, not as one more file — together with what the people who run the server
add in its configuration.

## What counts as guidance

Found in a repository by the conventions agents' clients use:

| File | In force |
|---|---|
| `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.github/copilot-instructions.md` at the root | for the whole repository |
| `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` in a folder | for that folder |
| `.claude/rules/**/*.md` | for the whole repository; or, with `paths:` in its frontmatter, for those paths |
| `.cursor/rules/**/*.mdc` | with `alwaysApply: true`, for the whole repository; with `globs:`, for those paths; otherwise read when it fits the task (its `description` says when) |
| `.claude/skills/*/SKILL.md` | a skill: named and described (`name`, `description`), read when it fits the task |

Patterns in `paths:` and `globs:` (a list, or a string separated by commas) read like
[`include` / `exclude`](configuration.md#patterns). Links are not followed; `@` imports inside a file are not
expanded; the same text in two files (a `CLAUDE.md` copied from `AGENTS.md`) is given once. A file is read up to 200 KB.

**Always from the default branch.** Guidance is read on the repository's default branch — never on the ref an agent is
reading. Text handed to an agent as instructions can steer it, and anyone who can push a branch could write one; the
default branch is the one a team reviews. Read as a file (`read_file`), any branch's `AGENTS.md` is shown as it is.

**It obeys `include` / `exclude`.** A guidance file outside them is not delivered; `--check` warns about it.

## Guidance from the configuration

Beside a repository's own files, the configuration can add guidance — for every repository, or for one:

```yaml
guidance:                              # for every repository on this server
  text: Say which commit you read.
  files: [/srv/notes/house-rules.md]   # files on the server's disk, read at start

repositories:
  - name: acme-rules                   # a repository that holds guidance about others
    path: /srv/code/acme-rules
    listed: false                      # a source of guidance only: agents don't see it

  - name: shop
    path: /srv/code/shop
    guidance:
      text: |
        Amounts are cents. Answer them in euros with two decimals.
      files: [shop-notes.md]           # relative to the configuration file's folder
      from:
        - repo: acme-rules             # its folder `shop/`, read by the same conventions —
          path: shop                   #   as if its AGENTS.md, rules and skills lived in `shop`
        - repo: acme-rules
          path: handbook
          files: ["*.md"]              # exactly these files, in force for the whole repository
      own: true                        # the repository's own guidance files (the default); false to ignore them
```

- **`from`** names another configured repository and a folder of it. Without `files`, the folder is read by the
  conventions above: its `AGENTS.md` is in force for the whole repository, a rule's `paths:` are paths of the
  repository it guides. With `files` (patterns under the folder), exactly those files are taken, each in force for
  the whole repository. A source is read on its own default branch, under its own `include` / `exclude`.
- **`listed: false`** keeps a repository out of `list_repos` and out of every tool — it is only read as a source.
- **`own: false`** — for a repository whose contributors you don't trust to instruct agents: its own files are ignored,
  and only what the configuration gives is delivered.

The order an agent reads: the server's `guidance`, the repository's `guidance` text and files, its `from` sources, then
its own files.

## How it reaches an agent

MCP keeps no session between requests, so the server can't know what an agent has read in its conversation. Instead:

- **Every answer about a repository with guidance starts with one line** saying so — call
  `read_guidance(repo=…)` once in the conversation and follow it.
- **An answer about a path that a scoped rule covers carries the rule** (when the scoped guidance for that path is short,
  up to 1,500 characters; longer, it is named with the call that reads it).
- **`read_guidance`** ([tools](tools.md#read_guidance)) gives all of it, or one piece by name — a skill when it fits.
- `list_repos` says which repositories have guidance; the server's instructions tell agents to follow it.

Guidance takes at most half of an answer; the answer keeps the rest.

## Checking it

`repo-reader-mcp --config config.yaml --check` lists each repository's guidance and warns about guidance files its
`include` / `exclude` keeps from agents.
