# Decisions

What is decided and why. Newest at the bottom; grep it.

## 2026-10-24 · An open-source, universal, read-only MCP for code

**Decision** (the author). A separate open-source project under the author's own GitHub, not any
company's: an MCP server for reading code with its git history, any branch, read-only — for any MCP client
(not tied to one model vendor) and any code host. A company's use of it — which repositories, tokens,
deployment — lives in that company's own repositories as configuration; nothing of any company is written
here.

**Why.** One tool many teams can use, configured rather than rewritten; the author's earlier
company-internal platform proved the parts (mirrors, search, safe grep, secret hiding) and showed they are
general.

## 2026-10-24 · The name keeps `mcp`; the documentation and hosting follow the author's own projects

- **The name is `repo-reader-mcp`** — the author's rule: `mcp` in the name and a meaning plain at a glance (the `-kit` names of
  the author's other projects were weighed and set aside); free on PyPI.
- **Documentation and hosting** as in the author's detectkit and pipelab: `docs/` the single source of a site built
  with Astro + Starlight; the site and an instance of the server deployed by `alexeiveselov92/pipelab`
  (`dev/DESIGN.md`, "Documentation, distribution and hosting"). Internal design, plan, decisions and research moved to
  `dev/` the same day, so the site never publishes them.

## 2026-10-24 · Python, the official MCP SDK, Apache-2.0, written fresh

- **Python 3.12 with uv**, the official MCP Python SDK (2.x: `MCPServer`, the in-process `Client` for tests).
  Installed with one command (`uvx`); the same stack as its sibling, semantic-warehouse-mcp.
- **Apache-2.0**: an explicit patent grant; the license companies take in most easily.
- **Written fresh**: the earlier platform's code belongs to the company it was written for. Its lessons are
  carried as design ([DESIGN.md](DESIGN.md), "Safety"), not as code.

## 2026-10-24 · Reading: committed content only, through git itself, never a checkout

**Decision** (the author agreed). The server reads commits — never a checkout's working files — through git's own
commands from a fixed set, arguments as a list, no Python git library. A ref an agent gives is checked (no leading `-`,
no whitespace) and resolved to a commit id; only the id reaches later commands. Paths are looked up in the commit's
tree, after `--`, literally.

**Why.** Reading commits is what lets many people read different branches of one repository at the same moment (no
working folder to share), and it keeps uncommitted files (a local `.env`) out. Git's own commands are the ones that
behave on a partial mirror (milestone 2). Resolving refs first closes a real hole: a branch can be named
`--output=<file>`, and `git diff` given that name writes the file (tried 2026-10-24).

## 2026-10-24 · include / exclude follow `.gitignore`'s habits; what is outside is never told

- A pattern with no `/` matches at any depth; a pattern naming a folder takes everything in it; `**` spans folders;
  brackets are literal. Chosen so an `exclude` written the way people write `.gitignore` keeps out what they meant.
- An excluded path is refused by name ("outside what this server serves"), judged by the path alone — never by whether
  it exists or changed. A commit's or a diff's file list says how many files it doesn't show, never which.

## 2026-10-24 · Answers in plain text that names the commit; capped; a few things left out on purpose

- Every answer is text with a header naming the repository, the ref and the commit; capped at
  `limits.answer_characters` (40,000 by default), with a note saying how to continue (`start_line`, `skip`, `path`).
- Left out on purpose: authors' emails (names only); file sizes in listings and renames in history (both make git
  fetch contents on a partial mirror); colour.

## 2026-10-24 · Repositories' guidance for agents (the author's request)

**Decision** (the author). A repository's rules for agents (`AGENTS.md`, `CLAUDE.md`, `.claude/rules/`, skills…) reach
an agent reading it through the server as instructions, the way a client loads them for a folder it is opened in. More
sources beside the repository's own: text in the configuration, files on the server's disk, and a folder of another
configured repository (`from`) — a company keeps its rules about a repository in its own repository. Read from the
default branch only; obeys `include` / `exclude`. Design in `dev/DESIGN.md`, "Repositories' guidance for agents".

**Why.** An agent outside the repository's folder loads none of its owners' rules, and those rules are what the
repository was written with. The default branch, because text handed to an agent as instructions can steer it, and any
branch can be pushed by anyone with access.

## 2026-10-24 · Groups of repositories by name, with exceptions (the author's requirement)

**Decision** (the author). A company has too many repositories to list: an entry can name a group —
`github: owner/prefix-*` (GitLab's groups alike) — resolved from the host on every sync (new repositories join,
archived ones leave), with `skip` (names or patterns) for what the pattern catches but shouldn't. The entry's settings
apply to every member. Milestone 2, with remote repositories.

## 2026-10-24 · Remote repositories before the docs site

**Decision** (the author). Milestone 2 is now remote repositories (mirrors, groups, Streamable HTTP); the docs site
follows as milestone 3.

**Why.** The target is a shared server over a company's many remote repositories; the reading built in milestone 1
serves it unchanged, and the site can publish the guide once that is true.

## 2026-10-24 · A history leaves out commits that changed only what is not served

**Decision** (the author). When a repository is served in part, `log` lists only commits that changed something
served, or nothing at all; `skip` counts what the agent sees. Commit messages stay as written.

**Why.** The refuting review showed a whole-branch history telling the activity on excluded paths (a commit
"Rotate secrets/…" touching only them). Messages are free text, so this narrows the leak rather than closing it — the
guide says so.

## 2026-10-24 · Guidance is announced by every answer, not given once a session

**Decision** (made while building; the author to confirm). Every answer about a repository with guidance starts with
one line naming `read_guidance`; a short scoped rule rides with each answer about its paths; the full guidance is read
with `read_guidance`.

**Why.** The design said "the first answer in a session carries it" — but MCP keeps no session between requests
(protocol revision 2026-07-28: each request is its own exchange; the SDK builds a new connection object per request).
A server can't know what an agent read, and on a shared server it can't tell agents apart. One line per answer
(~40 tokens) works on every transport; real Claude Code read the guidance on its own in every conversation and
followed it.

## 2026-10-24 · Contents of an older commit are fetched on purpose, for served paths only

**Decision** (proposed at the session's start; the author said "go" without choosing — to confirm). When a tool needs
the contents of a file at a commit whose contents the mirror lacks, the server fetches exactly those contents from the
host first (`Mirror.ensure`), after checking each path against include / exclude, and then reads. The alternative —
answering "not in the mirror" — was safer but leaves agents stuck on every older commit.

**Why.** "Never fetched by a reading command" stays true: the reading commands keep `protocol.allow=never`; the fetch
is a separate, deliberate step that names the objects and checks their paths in one place. Measured on a public
repository: five real questions fetched 29 contents on top of the 190 the sync took, none of an excluded path.

## 2026-10-24 · A mirror keeps every branch and tag unless `refs` narrows it; named from its URL

**Decision** (made while building). `refs` not given: every branch and tag (history without contents is cheap); the
default branch is always kept. `name` defaults to the URL's last part without `.git`. Mirrors live in
`~/.cache/repo-reader-mcp` by default — they can be rebuilt, so a cache folder — at `<name>-<digest of URL>.git`:
a URL change makes a new mirror instead of mixing two histories. The sync's status is a file beside the mirror, so
several server processes (one per person's agent over stdio) tell the same story.

## 2026-10-24 · With a token, no redirect is followed

**Decision** (found by a test while building). The token is an `Authorization` header set for the URL's host through
git's environment; git chooses its extra headers once per command and sends them with every request — after a redirect,
to the new host too. So with a token the sync sets `http.followRedirects=false`; a redirecting host fails the sync with
a message to give the URL it redirects to. Without a token nothing secret travels and git's default stays.

## 2026-10-24 · Attributes are never read from a commit

**Decision** (found while building). Every git call sets `attr.tree` to the empty tree. A bare repository reads
`.gitattributes` from HEAD; on a mirror that file may be excluded and absent (a diff failed), and anywhere it is text a
repository's authors write that changes how git reads it (diff drivers, textconv — already off by flags).

## 2026-10-24 · Blame on a mirror follows renames as far as the served files allow, and says where it stops

**Decision** (made while building; widened after the refuting review). Blame follows renames; for a rename with
changes git compares the file with every file deleted in that commit. The mirror fetches those when all are served and
follows the file into its old name (up to 8 hops); where one isn't served, blame reruns from that commit and says it
stopped there. A move without changes is followed by object id, reading nothing.

## 2026-10-24 · A mirror per configuration; mirrors share nothing

**Decision** (after the refuting review). A mirror's folder digest covers its URL, `refs`, `include` and `exclude`
(not the URL alone): two servers on one machine sharing the cache folder — or one configuration changed — would
otherwise read each other's branches and contents. A changed configuration refetches; the old mirror is left for the
operator to delete.

## 2026-10-24 · The refuting review's findings (all closed, each with a test that fails without its fix)

A served file replaced by a folder leaked the folder's excluded files into a diff (since milestone 1, local too); the
machine's `protocol.file.allow=always` let reading fetch; a tag of a tree made the sync fetch excluded contents; two
configurations shared a mirror; the machine's per-host `followRedirects` sent the token on; askpass and hooks ran with
the token in their environment; an unserved `.mailmap` broke every tool on a mirror; blame stopped at renames it could
follow, and failed on a path once a submodule; a contents id answered differently as a ref; a host's detached HEAD
left no default branch; a token over plain http and a URL with a query were accepted. Left as they are, noted: a
files-only diff on a mirror fetches the changed files' contents to count lines; fetches made for reading don't repack,
so packs pile up between syncs that move nothing.


## 2026-10-24 · Groups: listed by the host's API, addresses built by the server, archived ones leave

**Decision** (made while building, within the author's requirement). A group is listed by the host's API before every
sync. A member is named by its repository's own name (not `owner/name`): agents name repositories that way, and a
company's names are unique within its owner. A name already taken — by a repository listed one by one, or an earlier
group's member — keeps its first owner and the later one is left out, logged: listing a repository one by one is how a
member gets settings of its own. Archived repositories leave (as the author decided); forks stay (they are the owner's;
`skip` takes them out). Git addresses are built from the configured host and the listed path, never taken from the
listing; no redirect is followed and a next page must stay on the API — the token travels with these requests. The last
listing is kept on disk, so a restart serves at once and a host that can't be reached changes nothing. A group's
repository can't be a guidance source: a source should not come and go with a listing.

**Waiting for the author**: whether forks should be left out by default, and whether two members with the same name in
different GitLab subgroups should get longer names rather than the second being left out.

## 2026-10-24 · A mirror's digest includes the token's variable

**Decision** (made while building). A mirror's folder digest now covers the variable `token_env` names, beside the URL,
`refs`, `include` and `exclude`: a configuration without a token (or with another) must not serve what was fetched with
a token. Changing the variable refetches.

## 2026-10-24 · Streamable HTTP: stateless, JSON answers, a bearer token or a gateway

**Decision** (made while building). `--http [HOST:]PORT` serves at `/mcp` with no session kept and plain JSON answers —
what the protocol's newer revision expects, what gateways pass through, and what lets the server restart or run as
copies unseen. One bearer token, named by its variable (`http.token_env`), or `http.behind_gateway: true`; a non-loopback
address with neither is refused at start. The listening address is a command-line flag (where a deployment says it),
who may call is in the configuration. Per-person tokens and access per repository are later, with the author's server
instance (milestone 5).

## 2026-10-24 · The second refuting review's findings (groups and HTTP; all closed, each with a test)

An answer that wasn't HTTP (a broken status line echoing the token) or JSON nested too deep escaped as an exception: it
ended the background sync for good and printed the token — now every failure of a listing is a scrubbed listing error,
and a round that fails never ends the loop. Loopback addresses other than `127.0.0.1`, `localhost`, `::1` served with no
token and without the SDK's DNS-rebinding guard — now only those three serve open. A reverse proxy on the same machine
got 421 for its host name — with a token or a gateway, any host name is answered. `gitlab: group/**` didn't ask for
subgroups. A repository listed one by one and caught by a group was served twice, the copy ignoring the first entry's
exclude — now served once. A token over http to this machine went through the environment's proxy. A host's port
wasn't checked. A page sent a byte at a time held the listing — a page now has 60 seconds. A refresh landing in the
middle of a tool call broke it — a call now reads one set. A members file written by anything else was trusted — it is
checked again on load. A next page could hold `..`, and a host spelt differently in a next page was refused. A group
with `listed: false` served nothing — refused. Noted, not changed: two servers sharing a mirrors folder whose token
variables share a name but hold different tokens share mirrors (the docs say to give them different folders).
