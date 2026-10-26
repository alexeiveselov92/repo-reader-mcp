"""Every git command the server runs goes through here (dev/DESIGN.md, "Safety").

- Only commands from a fixed set, each run as a list of arguments — never through a shell.
- Flags that keep git from running a program a repository's configuration names (an external diff, a textconv filter,
  a signature checker) are added to every call of the commands that would.
- Git may not reach any host from a reading command: a partial clone's missing contents are never fetched behind the
  server's back. Only the sync reaches a host (`maintain`): by the one protocol of the repository's URL, with a token
  given in git's environment, never on its command line.
- The environment the server was started from can't redirect git to another repository or inject configuration.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

# The commands the server may run; each only reads.
COMMANDS = frozenset(
    {"rev-parse", "symbolic-ref", "for-each-ref", "ls-tree", "cat-file", "log", "diff", "blame", "merge-base", "grep"}
)

# The commands the sync runs on a mirror it keeps: making it, asking the host what it has, fetching, moving its refs —
# and reading the mirror to decide what to fetch. Only the network ones may reach a host.
MAINTAIN = frozenset(
    {"init", "config", "ls-remote", "fetch", "update-ref", "symbolic-ref", "for-each-ref", "ls-tree", "rev-list"}
)
NETWORK = frozenset({"ls-remote", "fetch"})

# Added right after the command, before anything else: an external diff program, a textconv filter and a signature
# checker are programs a repository's configuration names; blame's ignore-revs file is any file it names on the
# server's disk (git echoes its lines in an error); colour codes would garble the answer.
ALWAYS = {
    "diff": ("--no-ext-diff", "--no-textconv", "--no-color"),
    "log": ("--no-show-signature",),
    "blame": ("--no-textconv", "--no-ignore-revs-file"),
}

# Every protocol git knows. `protocol.allow=never` is only a default: a `protocol.<name>.allow=always` in the machine's
# configuration (a common workaround for `file`) would win over it, so each is refused by name as well.
PROTOCOLS = ("file", "git", "ssh", "http", "https", "ext", "fd")

# Configuration set on every call:
# - no transport at all, so a partial clone never fetches what it lacks;
# - nothing read from a commit's own files: a bare repository (a mirror) takes `.gitattributes` and `.mailmap` from its
#   HEAD — files a repository's authors write, which a mirror may not hold (the empty tree's id for attributes; in a
#   sha256 repository it names nothing, which git takes as the empty tree too);
# - no hooks: the sync's ref updates would run a `reference-transaction` hook the machine's configuration names.
CONFIG = (
    "protocol.allow=never",
    *(f"protocol.{name}.allow=never" for name in PROTOCOLS),
    "attr.tree=4b825dc642cb6eb9a060e54bf8d69288fbee4904",
    "mailmap.blob=",
    f"core.hooksPath={os.devnull}",
)

# The environment git is started with: the server's own, minus every GIT_* variable but the ones naming which
# configuration files the operator wants read, and minus a program git would run to ask for a password.
KEPT_GIT_VARIABLES = frozenset({"GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM"})
DROPPED_VARIABLES = frozenset({"SSH_ASKPASS"})
SET_VARIABLES = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_PAGER": "cat",
    "PAGER": "cat",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_LITERAL_PATHSPECS": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",  # a repository's replace refs would show other contents under a commit's id
    "LC_ALL": "C",
}

OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")  # an object id, sha1 or sha256

TIMEOUT_SECONDS = 30
NETWORK_TIMEOUT_SECONDS = 30 * 60  # a first fetch of a large history takes minutes
OUTPUT_BYTES = 4 * 1024 * 1024  # the most of one command's output read, unless a call asks for another limit


class GitError(RuntimeError):
    """Git refused or failed; `stderr` is git's own message."""

    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.stderr = stderr


@dataclass(frozen=True)
class Output:
    data: bytes
    cut: bool  # the output was longer than the limit asked for and was stopped there

    @property
    def text(self) -> str:
        return self.data.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class Access:
    """How the sync may reach a repository's host: the one protocol its URL uses, and configuration given through
    git's environment (a token's header) — never on the command line, where any user of the machine can read it."""

    protocol: str
    env: dict[str, str] = field(default_factory=dict, repr=False)


def environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if (not k.startswith("GIT_") or k in KEPT_GIT_VARIABLES) and k not in DROPPED_VARIABLES
    }
    env.update(SET_VARIABLES)
    env.update(extra or {})
    return env


def command(
    git_dir: str,
    args: Sequence[str],
    *,
    allowed: frozenset[str] = COMMANDS,
    protocol: str | None = None,
    config: Sequence[str] = (),
) -> list[str]:
    """The full command line for one call; refuses a command outside the fixed set. No transport is allowed, unless
    `protocol` names the one a network command of the sync may use."""
    if not args or args[0] not in allowed:
        raise GitError(f"`{args[0] if args else ''}` is not a command this server runs")
    items = [*CONFIG, *([f"protocol.{protocol}.allow=always"] if protocol else []), *config]
    options = [part for item in items for part in ("-c", item)]
    return ["git", *options, f"--git-dir={git_dir}", args[0], *ALWAYS.get(args[0], ()), *args[1:]]


def find_git_dir(path: str) -> str:
    """The git directory of the repository whose top is `path` (a checkout or a bare repository).

    A folder inside a repository is refused: the server would otherwise serve the whole repository above it.
    """
    real = os.path.realpath(path)

    def ask(*args: str) -> str:
        done = subprocess.run(
            ["git", "-C", real, "rev-parse", *args],
            env=environment(),
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
        if done.returncode != 0:
            stderr = done.stderr.decode("utf-8", errors="replace")
            if "dubious ownership" in stderr:  # git's own guard (`safe.directory`), as in a container with a mount
                raise GitError(
                    "it belongs to another user than the one the server runs as, and git won't read it: run the "
                    "server as the folder's owner, or name the folder in `safe.directory` of a git configuration the "
                    "server reads (GIT_CONFIG_GLOBAL)",
                    stderr,
                )
            said = stderr.strip().splitlines()
            raise GitError(f"it is not a git repository's top: {said[-1] if said else 'git said nothing'}", stderr)
        return done.stdout.decode("utf-8", errors="replace").strip()

    git_dir, bare = ask("--absolute-git-dir", "--is-bare-repository").splitlines()
    top = git_dir if bare == "true" else ask("--show-toplevel")
    if os.path.realpath(top) != real:
        raise GitError(f"it is inside the repository at {top}, not its top")
    return git_dir


def run(
    git_dir: str,
    args: Sequence[str],
    *,
    limit: int | None = None,
    ok_codes: Sequence[int] = (0,),
    input: bytes | None = None,
) -> Output:
    """Run one reading git command in a repository and return what it printed.

    Reading stops after `limit` bytes (`OUTPUT_BYTES` unless a call asks for another) — the command is stopped and the
    output marked cut — so no output (a huge diff, the file list of a huge tree) ever sits in memory whole.
    """
    # GIT_NO_LAZY_FETCH (git 2.44 and later): a missing object is never fetched, whatever the configuration says.
    env = environment({"GIT_NO_LAZY_FETCH": "1"})
    return _execute(command(git_dir, args), git_dir, env, limit=limit, ok_codes=ok_codes, input=input)


def stream(git_dir: str, args: Sequence[str], *, timeout: int = TIMEOUT_SECONDS) -> Iterator[bytes]:
    """Run one reading git command and give its output a line at a time, for as long as the caller reads: closing the
    iterator early stops git, and so does `timeout`. For an output read only as far as it is needed — with no limit of
    bytes, which would cut it where the caller can't choose."""
    env = environment({"GIT_NO_LAZY_FETCH": "1"})
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(
            command(git_dir, args), cwd=git_dir, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err
        )
        timed_out = threading.Event()

        def stop() -> None:
            timed_out.set()
            proc.kill()

        timer = threading.Timer(timeout, stop)
        timer.start()
        try:
            assert proc.stdout is not None
            yield from proc.stdout
            code = proc.wait()
        finally:
            timer.cancel()
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            assert proc.stdout is not None
            proc.stdout.close()
        err.seek(0)
        stderr = err.read().decode("utf-8", errors="replace").strip()
    if timed_out.is_set():
        raise GitError(f"git took longer than {timeout} seconds and was stopped", stderr)
    if code != 0:
        raise GitError(stderr.splitlines()[-1] if stderr else f"git exited with code {code}", stderr)


def maintain(
    git_dir: str,
    args: Sequence[str],
    *,
    access: Access | None = None,
    input: bytes | None = None,
    limit: int | None = None,
    config: Sequence[str] = (),
    timeout: int | None = None,
) -> Output:
    """Run one command of the sync on a mirror. A network command reaches the host by `access` — its protocol alone,
    its environment; every other command reaches nothing."""
    network = access is not None and bool(args) and args[0] in NETWORK
    cmd = command(git_dir, args, allowed=MAINTAIN, protocol=access.protocol if network else None, config=config)
    env = environment(access.env if network else None)
    timeout = timeout or (NETWORK_TIMEOUT_SECONDS if network else TIMEOUT_SECONDS)
    return _execute(cmd, git_dir, env, limit=limit, input=input, timeout=timeout)


def _execute(
    cmd: list[str],
    cwd: str,
    env: dict[str, str],
    *,
    limit: int | None = None,
    ok_codes: Sequence[int] = (0,),
    input: bytes | None = None,
    timeout: int = TIMEOUT_SECONDS,
) -> Output:
    limit = OUTPUT_BYTES if limit is None else limit
    with tempfile.TemporaryFile() as err, tempfile.TemporaryFile() as given:
        if input is not None:
            given.write(input)
            given.seek(0)
        stdin = given if input is not None else subprocess.DEVNULL
        try:
            proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=stdin, stdout=subprocess.PIPE, stderr=err)
        except OSError as error:  # a command line longer than the system takes, and the like
            raise GitError(f"git could not be started: {error.strerror or error}") from None
        timed_out = threading.Event()

        def stop() -> None:
            timed_out.set()
            proc.kill()

        timer = threading.Timer(timeout, stop)
        timer.start()
        try:
            assert proc.stdout is not None
            data = proc.stdout.read(limit + 1)
            cut = len(data) > limit
            if cut:
                proc.kill()
                data = data[:limit]
            proc.stdout.close()
            code = proc.wait()
        finally:
            timer.cancel()
        err.seek(0)
        stderr = err.read().decode("utf-8", errors="replace").strip()
    if cut:
        return Output(data, True)
    if timed_out.is_set():
        raise GitError(f"git took longer than {timeout} seconds and was stopped", stderr)
    if code not in ok_codes:
        raise GitError(stderr.splitlines()[-1] if stderr else f"git exited with code {code}", stderr)
    return Output(data, False)
