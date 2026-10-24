# Safety

What repo-reader-mcp never does, and how. Each protection has a test that fails when the protection is taken out
(`tests/test_safety.py`).

## It never changes a repository

- **Only reading commands, from a fixed set**: `rev-parse`, `symbolic-ref`, `for-each-ref`, `ls-tree`, `cat-file`,
  `log`, `diff`, `blame`, `merge-base`. Any other command is refused before git starts.
- **No shell.** Every command is a list of arguments handed to git directly; nothing an agent writes is ever read by a
  shell.
- **It never checks anything out.** Files are read from commits, never from a working folder — which is also why many
  people can read different branches of the same repository at the same moment.

## An agent's input can't become a command

- **A ref is checked, then resolved to a commit id.** A ref starting with `-`, or holding spaces or control characters,
  is refused. Every command after that gets the commit id, never the agent's text. This matters because a branch *can*
  be named like an option — anyone who can push can create a branch called `--output=/some/file`, and `git diff` given
  that name writes a file. Here, that branch is just read at the commit it points at.
- **A path is plain and literal.** `..`, `.` and empty parts are refused; paths reach git after `--`, read literally
  (no wildcard or pathspec magic), and are looked up inside the commit's tree — never on the disk.

## It never runs a program a repository names

A repository's configuration and its `.gitattributes` can name programs git would run while reading: an external diff
program (for all files, or for some through a diff driver), a textconv filter (which git applies in a diff and in
blame), a signature checker (which `git log` calls when the configuration says to show signatures). It can also name a
file anywhere on the server's disk for blame to read (`blame.ignoreRevsFile` — git repeats its lines in an error). The
server turns each off on every call (`--no-ext-diff`, `--no-textconv`, `--no-show-signature`,
`--no-ignore-revs-file`) — a diff is always of the file's own text.

## It never reaches the network

Every command runs with no transport allowed (`protocol.allow=never`). A repository that is a partial clone — missing
some files' contents — is not completed behind the server's back: reading a missing content answers that it isn't in
the local copy.

## The environment it was started from can't redirect it

Git variables in the server's environment (`GIT_DIR`, `GIT_NAMESPACE`, `GIT_OBJECT_DIRECTORY`, injected configuration,
an external diff…) are dropped before git starts. Kept: `GIT_CONFIG_GLOBAL`, `GIT_CONFIG_SYSTEM`,
`GIT_CONFIG_NOSYSTEM` — the operator's choice of which configuration files git reads.

## It serves only what it is told to

`include` and `exclude` ([configuration](configuration.md)) are applied by every tool: an excluded path is never
listed, never in a diff or a file list of a commit, never read or blamed, and a folder of excluded files answers as a
folder that isn't there. Narrowing a history or a diff to an excluded path is refused, judged by the path alone — so the
answer never tells whether it exists or changed. A commit that changed excluded files says how many it doesn't show —
never which.

What it doesn't hide: **commit messages** are shown as their authors wrote them, and the history of a whole branch
(`log` without a `path`) lists every commit — including one that changed only excluded paths, whose subject may name
them. Contents of excluded files never appear.

## Sizes

Every answer is capped (`limits.answer_characters`) and says when it was cut. Git's output is read up to 4 MB per
command (a file up to 10 MB) and the command stopped there — a huge tree, history or diff never sits in memory whole;
the answer says it is partial. One git command is stopped after 30 seconds.

## Not yet

- **Secrets in files are not hidden yet.** A key committed to a served file is shown as it is. Until the secret scan
  comes (`dev/PLAN.md`, milestone 4), keep such files out with `exclude` (`*.pem`, `*.env`, `secrets`).
- Remote repositories, their tokens and their schedule come in milestone 2; tokens will travel in git's environment
  only, never on a command line or in an error.
