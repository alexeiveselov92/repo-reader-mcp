"""Every git command the server runs goes through here (dev/DESIGN.md, "Safety").

- Only commands from a fixed set, each run as a list of arguments — never through a shell.
- Flags that keep git from running a program a repository's configuration names (an external diff, a textconv filter,
  a signature checker) are added to every call of the commands that would.
- Git may not reach any host: a partial clone's missing contents are never fetched behind the server's back.
- The environment the server was started from can't redirect git to another repository or inject configuration.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import threading
from collections.abc import Sequence
from dataclasses import dataclass

# The commands the server may run; each only reads.
COMMANDS = frozenset(
    {"rev-parse", "symbolic-ref", "for-each-ref", "ls-tree", "cat-file", "log", "diff", "blame", "merge-base"}
)

# Added right after the command, before anything else: an external diff program, a textconv filter and a signature
# checker are programs a repository's configuration names; blame's ignore-revs file is any file it names on the
# server's disk (git echoes its lines in an error); colour codes would garble the answer.
ALWAYS = {
    "diff": ("--no-ext-diff", "--no-textconv", "--no-color"),
    "log": ("--no-show-signature",),
    "blame": ("--no-textconv", "--no-ignore-revs-file"),
}

# Configuration set on every call: no transport at all, so a partial clone never fetches what it lacks.
CONFIG = ("protocol.allow=never",)

# The environment git is started with: the server's own, minus every GIT_* variable but the ones naming which
# configuration files the operator wants read.
KEPT_GIT_VARIABLES = frozenset({"GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM"})
SET_VARIABLES = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_PAGER": "cat",
    "PAGER": "cat",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_LITERAL_PATHSPECS": "1",
    "LC_ALL": "C",
}

TIMEOUT_SECONDS = 30
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


def environment() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k in KEPT_GIT_VARIABLES}
    env.update(SET_VARIABLES)
    return env


def command(git_dir: str, args: Sequence[str]) -> list[str]:
    """The full command line for one call; refuses a command outside the fixed set."""
    if not args or args[0] not in COMMANDS:
        raise GitError(f"`{args[0] if args else ''}` is not a command this server runs")
    config = [part for item in CONFIG for part in ("-c", item)]
    return ["git", *config, f"--git-dir={git_dir}", args[0], *ALWAYS.get(args[0], ()), *args[1:]]


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
            message = done.stderr.decode("utf-8", errors="replace").strip().splitlines()
            raise GitError(message[-1] if message else "not a git repository", done.stderr.decode(errors="replace"))
        return done.stdout.decode("utf-8", errors="replace").strip()

    git_dir, bare = ask("--absolute-git-dir", "--is-bare-repository").splitlines()
    top = git_dir if bare == "true" else ask("--show-toplevel")
    if os.path.realpath(top) != real:
        raise GitError(f"it is inside the repository at {top}, not its top")
    return git_dir


def run(git_dir: str, args: Sequence[str], *, limit: int | None = None, ok_codes: Sequence[int] = (0,)) -> Output:
    """Run one git command in a repository and return what it printed.

    Reading stops after `limit` bytes (`OUTPUT_BYTES` unless a call asks for another) — the command is stopped and the
    output marked cut — so no output (a huge diff, the file list of a huge tree) ever sits in memory whole.
    """
    limit = OUTPUT_BYTES if limit is None else limit
    cmd = command(git_dir, args)
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(
            cmd, cwd=git_dir, env=environment(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err
        )
        timed_out = threading.Event()

        def stop() -> None:
            timed_out.set()
            proc.kill()

        timer = threading.Timer(TIMEOUT_SECONDS, stop)
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
        raise GitError(f"git took longer than {TIMEOUT_SECONDS} seconds and was stopped", stderr)
    if code not in ok_codes:
        raise GitError(stderr.splitlines()[-1] if stderr else f"git exited with code {code}", stderr)
    return Output(data, False)
