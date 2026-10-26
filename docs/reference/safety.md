# Safety

What repo-reader-mcp never does, and how. Each protection has a test that fails when the protection is taken out
(`tests/test_safety.py`).

## It never changes a repository

- **Only reading commands, from a fixed set**: `rev-parse`, `symbolic-ref`, `for-each-ref`, `ls-tree`, `cat-file`,
  `log`, `diff`, `blame`, `merge-base`, `grep`. Any other command is refused before git starts.
- **The sync has its own fixed set**, used only on the mirrors the server keeps in its own folder: `init`, `config`,
  `ls-remote`, `fetch`, `update-ref`, `symbolic-ref`, `for-each-ref`, `ls-tree`, `rev-list`. Never `push`; nothing it
  runs touches a repository that isn't the server's own mirror.
- **No shell.** Every command is a list of arguments handed to git directly; nothing an agent writes is ever read by a
  shell.
- **It never checks anything out.** Files are read from commits, never from a working folder — which is also why many
  people can read different branches of the same repository at the same moment.

## An agent's input can't become a command

- **A ref is checked, then resolved to a commit id.** A ref starting with `-`, or holding spaces or control characters,
  is refused. Every command after that gets the commit id, never the agent's text. This matters because a branch *can*
  be named like an option — anyone who can push can create a branch called `--output=/some/file`, and `git diff` given
  that name writes a file. Here, that branch is just read at the commit it points at.
- **A ref is a name or an id, nothing more of git's syntax.** A branch, a tag or a remote-tracking branch — looked up
  among those `list_refs` shows, never a stash, a note, a reflog or a ref fetched elsewhere — or a commit's id (an
  annotated tag's too, never a file's contents), then `~N` / `^N` steps. An id is read only when a branch, a tag or
  HEAD has its commit: a stash's commits, a commit amended away or a branch deleted are still in a repository, and
  never read by their id. A whole id is always an id — a branch named like one never takes its place — and the start of
  one that is also a name is refused. The rest of git's revision syntax is refused:
  `main^{/text}` and `:/text` search commit messages, so whether one resolved would confirm a guess at a secret a
  message holds, a character at a time; `main@{1}` reads a reflog, `main:file` a file, `a..b` is a range.
- **A repository's replace refs are ignored.** git would show a replacement's contents under a commit's id, which
  anyone who can push a ref could set; the server reads every object as it is.
- **A path is plain and literal.** `..`, `.` and empty parts are refused; paths reach git after `--`, read literally
  (no wildcard or pathspec magic), and are looked up inside the commit's tree — never on the disk.

## It never runs a program a repository names

A repository's configuration and its `.gitattributes` can name programs git would run while reading: an external diff
program (for all files, or for some through a diff driver), a textconv filter (which git applies in a diff and in
blame), a signature checker (which `git log` calls when the configuration says to show signatures). It can also name a
file anywhere on the server's disk for blame to read (`blame.ignoreRevsFile` — git repeats its lines in an error). The
server turns each off on every call (`--no-ext-diff`, `--no-textconv`, `--no-show-signature`,
`--no-ignore-revs-file`) — a diff is always of the file's own text.

Nothing is read from a commit's own files to change how git reads it: no attributes (`attr.tree` is the empty tree)
and no `.mailmap` (`mailmap.blob` is empty). In a bare repository — every mirror is one — git would take
`.gitattributes` and `.mailmap` from the default branch: files the repository's authors write, which a mirror may not
even hold. No hook runs either (`core.hooksPath` is empty): the sync moves refs, which would run a hook the machine's
configuration names.

## Reading never reaches the network

Every reading command runs with no transport allowed — `protocol.allow=never`, and each protocol refused by name as
well (`protocol.file.allow=never`, …): a `protocol.<name>.allow=always` in the machine's git configuration would
otherwise win over the default. And git is told never to fetch a missing object (`GIT_NO_LAZY_FETCH`, obeyed by git
2.44 and later). A repository that is a partial clone — missing some files' contents — is not completed behind the
server's back: for a local repository, reading a missing content answers that it isn't in the local copy.

Only the [sync](../remote-repositories.md) reaches a host, and only for the mirrors it keeps:

- **By the URL's own protocol, alone.** A network command allows exactly the protocol of the configured URL — a URL
  rewritten on the way (`insteadOf` in the machine's git configuration) can't switch it to another, even one the
  machine's configuration allows. Remote helpers (`ext::`, which runs a command) are refused in the configuration.
- **Contents of served paths only.** The sync fetches history without contents, then the contents of the files
  `include` / `exclude` serve. Before a tool reads a file's older version, the contents it needs are fetched on purpose
  — and the path is checked again there: whatever asks, nothing outside `include` / `exclude` is fetched. A diff counts
  lines of the served files only, so git never needs the others.
- **No submodules, no tags it wasn't asked for**: `--recurse-submodules=no`, `--no-tags`. A tag of a folder or of a
  file's contents (rather than of a commit) is not kept: its paths are not the repository's, so include / exclude
  can't judge them. (Git sends what a ref names: a tag of a file's contents brings that one file, which nothing reads.)
- **A mirror per configuration.** A mirror's folder is named by a digest of its URL, `refs`, `include`, `exclude` and
  the name of the token's variable: another server on the same machine, or this configuration changed, gets a mirror of
  its own — never the branches or contents another configuration took, nor what was fetched with a token by a
  configuration that names none. (Two servers whose variables share a name but hold different tokens would share it:
  give them different mirror folders.)
- **A file's id tells nothing.** A file's id is its contents' digest; given as a ref, the id of contents a mirror lacks
  answers as an unknown name does, so an agent can't confirm contents it guessed.

## A group's listing

A [group](../remote-repositories.md#groups) is listed by the host's API — reading requests only, to that API only:

- **No redirect is followed**, and a next page that points outside the API (another host, or another path on it) is
  refused: the token travels with these requests.
- **Addresses come from the configuration**: a repository's git address is built from the configured host and the path
  the listing gives — never taken from the listing (its `clone_url` could name any host). A path with a `.` or `..`
  part, or characters a repository's name can't have, is left out; so is one outside the owner the entry names.
- **The token never shows**: not in the kept listing, the log, `--check` or an error — a host's message that echoes
  it has it taken out. A token sent over plain http (to this machine only) never goes through a proxy the environment
  names.
- **A host can fail its listing, nothing more**: an answer that isn't HTTP, or isn't JSON the server reads, fails that
  listing — the group keeps what it had — and never stops the syncs; a page is stopped after 60 seconds however slowly
  it comes.
- **The kept listing is checked again** when read at start, as if the host had just sent it: a file written there by
  anything else can't add a repository the entry doesn't take.
- **A repository is served once.** A group's repository that is also listed one by one (at the same address, however
  spelt) is left out of the group: served twice, the copy would ignore the first entry's `include` / `exclude`.

## Tokens

- **Named, never written**: the configuration holds the name of the environment variable (`token_env`); a URL with
  credentials, a query or a fragment in it is refused (agents are shown the URL).
- **Over https**: a token with a plain `http://` URL is refused (it would show on the way), except to this machine.
- **In git's environment only**: the token reaches git as an `Authorization` header in its environment — never on a
  command line (any user of the machine can list those), in a URL, in a mirror's configuration or files, in the sync's
  status, in a log line or an answer. An error is scrubbed of it, in every form it travels in.
- **To its host only**: the header is set for the URL's host, and with a token **no redirect is followed** — git keeps
  a header for every request of a command, wherever a redirect sends them, so a host that redirects elsewhere would
  hand the token on (found by a test of this server, 2026-10-24). The setting is made for the repository's full URL,
  the closest match there is, so the machine's git configuration can't turn redirects back on for that host.
- **No one else's credentials, no one else's programs**: with a token, the credential helpers of the server's account
  are switched off for the sync — a refused token is never followed by credentials stored for someone else, nor
  stored by a helper — and so is any program asking for a password (`core.askPass`, `SSH_ASKPASS`), which would run
  with the token in its environment.

## Over HTTP, only who may call

- **A bearer token** on every request (`http.token_env`), compared in constant time; any other request is answered
  `401` with nothing else. The one exception is `GET /health`, exactly that path. It says only whether the server
  is ready (`{"status": "ready"}` or `"syncing"`), names no repository and reads none ([in a
  container](../running-in-a-container.md#health)).
- **Never open by accident**: on an address other than the machine's own, the server won't start without a token or
  `http.behind_gateway: true`.
- **On the machine's own address** — exactly `127.0.0.1`, `localhost` or `::1` — no token is needed, and only requests
  addressed to it by those names are answered: a web page can't reach it through a domain name that resolves there.
  Any other address, `127.0.0.2` included, needs a token or a gateway.
- **One call, one set**: a tool reads the repositories as they were when the call began, whatever a group's listing
  changes meanwhile.

## The environment it was started from can't redirect it

Git variables in the server's environment (`GIT_DIR`, `GIT_NAMESPACE`, `GIT_OBJECT_DIRECTORY`, injected configuration,
an external diff…) are dropped before git starts — for reading and for the sync. Kept: `GIT_CONFIG_GLOBAL`, `GIT_CONFIG_SYSTEM`,
`GIT_CONFIG_NOSYSTEM` — the operator's choice of which configuration files git reads.

## It serves only what it is told to

Search and grep give git the served files by name, and no other: a file include / exclude keep out is never read by
the search, so its lines can't come back — and an agent's pattern reaches git only after `-e`, as text to find, never
as an option.

`include` and `exclude` ([configuration](configuration.md)) are applied by every tool: an excluded path is never
listed, never in a diff or a file list of a commit, never read or blamed, and a folder of excluded files answers as a
folder that isn't there. A diff keeps only the sections of the files asked for: git takes a path as a folder too, so
where a served file `config` was replaced by a folder holding an excluded `config/prod.env`, that file would come with
it — instead `config` is listed and its diff not shown (found by the refuting review, 2026-10-24). Narrowing a history or a diff to an excluded path is refused, judged by the path alone — so the
answer never tells whether it exists or changed. A commit that changed excluded files says how many it doesn't show —
never which.

A history (`log`, `search_commits`) lists only commits that changed something served (or nothing at all): a commit
that changed only excluded paths is left out. What it doesn't hide: **commit messages** are shown as their authors wrote them — a commit
that changed a served file and an excluded one may name both in its message.

## Guidance can't be planted from a branch

A repository's [guidance for agents](guidance.md) is presented to agents as instructions, so it is read only on the
default branch — the one a team reviews — never on the branch an agent is reading; a repository whose contributors
shouldn't instruct agents is configured with `own: false`, and one whose rules were written for another job (its
developers' process) takes only some of them with `own: [patterns]`. Guidance obeys `include` / `exclude` like any
other file.

## Sizes

Every answer is capped (`limits.answer_characters`) and says when it was cut. Git's output is read up to 4 MB per
command (a file up to 10 MB) and the command stopped there — a huge tree, history or diff never sits in memory whole;
the answer says it is partial. One reading git command is stopped after 30 seconds; one that reaches a host, after 30
minutes. A request to a host's API is stopped after 30 seconds and read up to 32 MB a page; a group lists up to 20,000
repositories.

## Secrets found in files are hidden

Repositories hold secrets they shouldn't — a token in a config, a password in a URL, a private key someone committed.
Every answer, and every error, passes through a filter that replaces each value that looks like a secret with
`[hidden: <what>]`, and the answer ends saying how many it hid:

```
  3	  github_token: "[hidden: GitHub token]"
  4	  database: postgres://shop:[hidden: password]@db.example.com/shop

[2 values that look like secrets are hidden as `[hidden: …]` — this server never shows them.]
```

- **What it hides**: providers' keys and tokens by their own formats (AWS, GitHub, GitLab, Slack, Stripe, Google,
  OpenAI, Anthropic, npm, Telegram, JWTs); the password in `scheme://user:password@host` (an empty user too, as Redis
  writes it); a private key — its whole block where the file is at hand (`read_file`, `blame`, `search`, `grep`, and
  a diff, back to the hunk's start when the hunk begins inside it), a key written on one line in base64 (as a
  kubeconfig holds it), and any run of key material elsewhere; a value given to a setting named for a secret (`password`, `secret`, `token`, `api_key`, `access_key`,
  `private_key` — `API_KEY=…`, `"client_secret": "…"`) unless it is a reference or a placeholder (`os.environ[…]`,
  `${VAR}`, `changeme`, a name); a password written in prose ("the password is …").
- **Everywhere**: files, blame, diffs and commits, histories' messages, search and grep hits, guidance — the filter is
  the last thing every tool's answer passes through, so a tool added later can't skip it.
- **A guessed secret can't be confirmed** — by a match, a missing one, or the lines around it. A plain text `search` or
  `grep` found is kept only where an occurrence of it lies clear of the hidden values; a regular expression never
  matches a line holding one (the server doesn't match it again in another dialect, which could be tricked into
  matching the gap a hidden value leaves). The answer is then what git would have given had the dropped lines not
  matched: the limit of matches a file counted after them, the lines around the matches kept alone. A commit whose
  message holds a hidden value isn't found by its message at all — by `log`'s `message` or by `search_commits` — and
  is left out before the answer is cut, so it never shifts what is shown or whether more is said to follow.
- **The rules lean towards hiding**: a value hidden by mistake (a long base64 line, a test fixture shaped like a key)
  costs a look at the host; a value shown costs a rotation. What they can't see is not hidden: a secret with no
  recognisable shape, in no setting named for one — keep such files out with `exclude`.

## Files named for credentials are never served

`.env` (and `.env.local`, `.env.production`… — not `.env.example`, `.env.sample`, `.env.template`), `*.env`, `.envrc`,
`*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.jks`, `*.keystore`, `*.kdbx`, `*.ppk`, `*.tfstate`, `id_rsa`, `id_dsa`,
`id_ecdsa`, `id_ed25519` (and `id_rsa_github`…, not `.pub`), `.netrc`, `.pgpass`, `.pypirc`, `.git-credentials` are
treated as `exclude` takes them, in every repository: never listed, read, searched or diffed — and never
fetched into a mirror. A repository whose such files are meant to be read says `serve_credential_files: true`; the
secrets in them are still hidden. One difference from `exclude`: a history is not narrowed for them alone — a commit
that changed only such a file is still listed, with its message (never the file), since narrowing would mean reading
the files every commit changed. To leave such commits out, name the files in `exclude`.
