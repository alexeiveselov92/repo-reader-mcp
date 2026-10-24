"""Remote repositories, mirrored (docs/remote-repositories.md).

A mirror is a bare partial clone in the server's own folder: the commits and folders of the whole history of the
branches and tags it keeps, and the contents of only the files it serves. Every reading tool reads it as it reads a
local repository, with no transport allowed. Two things fetch, and nothing else:

- the sync, at start and on a schedule: it asks the host what it has, moves the mirror's branches and tags to match
  (force-pushes followed, deleted ones dropped), and fetches the served files' contents at the tips that moved;
- `ensure`, on purpose, before a tool reads contents the mirror lacks (an older commit) — of served paths only.

A token travels in git's environment, as a header for the repository's host only — never on a command line, in a URL,
in the mirror's configuration, in its status or in an error.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import tempfile
import threading
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from pathlib import Path
from urllib.parse import urlsplit

from .config import RepositoryConfig
from .git import OID, Access, GitError, Output, maintain

try:
    import fcntl
except ImportError:  # no flock (Windows): one server process per mirror folder is the operator's to keep
    fcntl = None

log = logging.getLogger("repo_reader_mcp")

NULL = frozenset({"0" * 40, "0" * 64})
LIST_BYTES = 64 * 1024 * 1024  # a host's list of refs, or a tip's list of files, is read up to this
WORKERS = 4  # mirrors synced at once
ON_DEMAND_TIMEOUT_SECONDS = 120  # a fetch made while an agent waits
# Fetching contents on demand runs no maintenance (a sync does), and asks for exactly the objects named.
ON_DEMAND = ("fetch.negotiationAlgorithm=noop", "gc.auto=0", "maintenance.auto=false")
# A sync's own maintenance runs inside it — under its lock and its timeout — not detached after it.
IN_SYNC = ("gc.autoDetach=false", "maintenance.autoDetach=false")

_thread_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


class SyncError(Exception):
    """A mirror could not be made or brought up to date; the message is git's reason, with any token taken out."""


@dataclass(frozen=True)
class Status:
    synced: str | None = None  # when the last sync that worked ended
    failed: str | None = None  # when the last sync failed, if it did after that
    error: str | None = None
    skipped: dict[str, str] = field(default_factory=dict)  # tags of no commit, by name: the object each named


def _when(stamp: str | None) -> str:
    if not stamp:
        return "never"
    try:
        return datetime.fromisoformat(stamp).astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return stamp


def _plural(count: int, word: str, many: str | None = None) -> str:
    return f"{count} {word if count == 1 else many or word + 's'}"


class Mirror:
    """One remote repository's mirror: making it, keeping it fresh, and fetching what a tool is about to read."""

    def __init__(self, config: RepositoryConfig):
        assert config.remote is not None
        self.config = config
        self.remote = config.remote
        self.name = config.name
        self.git_dir = Path(config.git_dir)
        self.lock_file = self.git_dir.with_suffix(".lock")
        self.status_file = self.git_dir.with_suffix(".status.json")

    @property
    def ready(self) -> bool:
        """Whether the first sync has made the mirror (it is moved into place only once complete)."""
        return (self.git_dir / "HEAD").is_file()

    # --- reaching the host ----------------------------------------------------------------------------------------

    def _token(self) -> str | None:
        if not self.remote.token_env:
            return None
        token = os.environ.get(self.remote.token_env, "")
        if not token:
            raise SyncError(f"the variable {self.remote.token_env} is not set in the server's environment")
        return token

    def access(self) -> Access:
        """The protocol of the URL alone, and the token — when there is one — as an `Authorization` header for the
        URL's host, given through git's environment. With a token:

        - no redirect is followed: git keeps a header it chose at the start for every later request, wherever a
          redirect sends them, so a host that redirects elsewhere would hand the token on (found by a test, 2026-10-24).
          Set for the repository's full URL — the closest match git knows, which a setting of the machine's for the
          host can't override;
        - the server account's credential helpers are switched off — a refused token is never followed by credentials
          stored for someone else, nor stored by a helper — and so is a program asking for a password (`core.askPass`),
          which would run with the token in its environment."""
        token = self._token()
        if token is None:
            return Access(self.remote.protocol)
        basic = base64.b64encode(f"{self.remote.token_user}:{token}".encode()).decode()
        parts = urlsplit(self.remote.url)
        host = f"{parts.scheme.lower()}://{parts.netloc}/"
        config = [
            ("credential.helper", ""),
            ("core.askPass", ""),
            (f"http.{self.remote.url}.followRedirects", "false"),
            (f"http.{host}.extraHeader", f"Authorization: Basic {basic}"),
        ]
        env = {"GIT_CONFIG_COUNT": str(len(config))}
        for i, (key, value) in enumerate(config):
            env[f"GIT_CONFIG_KEY_{i}"] = key
            env[f"GIT_CONFIG_VALUE_{i}"] = value
        return Access(self.remote.protocol, env)

    def scrub(self, text: str) -> str:
        """Text with the token taken out, in every form it travels in."""
        try:
            token = self._token()
        except SyncError:
            return text
        if not token:
            return text
        user = f"{self.remote.token_user}:{token}"
        for secret in (base64.b64encode(user.encode()).decode(), user, token):
            text = text.replace(secret, "***")
        return text

    def _git(
        self,
        git_dir: Path,
        *args: str,
        network: bool = False,
        input: bytes | None = None,
        limit: int | None = None,
        config: tuple[str, ...] = (),
        timeout: int | None = None,
    ) -> Output:
        try:
            access = self.access() if network else None
            return maintain(str(git_dir), args, access=access, input=input, limit=limit, config=config, timeout=timeout)
        except GitError as error:
            reason = self.scrub(str(error).removeprefix("fatal: "))
            if network and self.remote.token_env and "returned error: 30" in reason:
                reason += " — the host redirects elsewhere, which the server doesn't follow with a token: give `url` "
                reason += "as the address it redirects to"
            raise SyncError(reason) from None

    # --- the sync -------------------------------------------------------------------------------------------------

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """One writer per mirror: across this process's threads, and across processes sharing the folder."""
        with _guard:
            lock = _thread_locks.setdefault(str(self.lock_file), threading.Lock())
        with lock:
            self.git_dir.parent.mkdir(parents=True, exist_ok=True)
            with open(self.lock_file, "a+b") as handle:
                if fcntl is not None:
                    fcntl.flock(handle, fcntl.LOCK_EX)
                yield

    def _make(self, work: Path) -> None:
        """An empty bare repository that knows it is a partial clone of the URL — and holds no credentials."""
        if work.exists():
            shutil.rmtree(work)  # a first sync that stopped half-way
        work.mkdir(parents=True)
        self._git(work, "init", "--bare", "--quiet", "--template=")
        for key, value in (
            ("core.repositoryformatversion", "1"),
            ("extensions.partialClone", "origin"),
            ("remote.origin.url", self.remote.url),
            ("remote.origin.promisor", "true"),
            ("remote.origin.partialCloneFilter", "blob:none"),
        ):
            self._git(work, "config", key, value)

    def _remote_refs(self, work: Path) -> tuple[str | None, dict[str, str]]:
        """The host's default branch (as `refs/heads/…`) and its branches and tags, each with the object it names."""
        out = self._git(work, "ls-remote", "--symref", "origin", network=True, limit=LIST_BYTES)
        if out.cut:
            raise SyncError("the host lists more branches and tags than the server reads")
        default, head, refs = None, None, {}
        for line in out.text.splitlines():
            first, _, name = line.partition("\t")
            if first.startswith("ref: ") and name == "HEAD":
                target = first.removeprefix("ref: ")
                default = target if target.startswith("refs/heads/") else None
            elif OID.fullmatch(first) and name == "HEAD":
                head = first
            elif OID.fullmatch(first) and name.startswith(("refs/heads/", "refs/tags/")) and not name.endswith("^{}"):
                refs[name] = first
        if default is None and head is not None:
            # A host whose HEAD is a commit, not a branch: the branch at that commit, `main` or `master` first.
            at_head = sorted(
                (name for name, oid in refs.items() if oid == head and name.startswith("refs/heads/")),
                key=lambda name: (name not in ("refs/heads/main", "refs/heads/master"), name),
            )
            default = at_head[0] if at_head else None
        return default, refs

    def keeps(self, refname: str, default: str | None) -> bool:
        """Whether the mirror keeps a branch or tag: the default branch always; the others `refs` names (all, when it
        doesn't say)."""
        if refname == default or self.remote.refs is None:
            return True
        short = refname.split("/", 2)[2]
        return any(fnmatchcase(short, pattern) for pattern in self.remote.refs)

    def _local_refs(self, work: Path) -> dict[str, str]:
        out = self._git(work, "for-each-ref", "--format=%(objectname) %(refname)", "refs/heads", "refs/tags")
        return {name: oid for oid, _, name in (line.partition(" ") for line in out.text.splitlines()) if name}

    def _not_commits(self, work: Path, names: list[str]) -> list[str]:
        """The refs among `names` that don't lead to a commit — a tag of a tree or of a file's contents."""
        out = self._git(
            work, "for-each-ref", "--format=%(refname) %(objecttype) %(*objecttype)", *names, limit=LIST_BYTES
        )
        odd = []
        for line in out.text.splitlines():
            name, kind, peeled = (line.split(" ") + ["", ""])[:3]
            if (peeled or kind) != "commit":
                odd.append(name)
        return odd

    def _served_at(self, work: Path, tips: Iterable[str]) -> list[tuple[str, str]]:
        """The contents (object, path) of the files at some commits — before include / exclude, which `ensure`
        applies. Paths are always from a commit's root (a tag of a folder would list paths from inside it)."""
        found = []
        for tip in sorted(set(tips)):
            try:
                out = self._git(work, "ls-tree", "-r", "-z", "--full-tree", f"{tip}^{{commit}}", limit=LIST_BYTES)
            except SyncError as error:
                log.info("%s: no files read at %s: %s", self.name, tip[:12], error)
                continue
            records = out.text.split("\0")
            for record in records[:-1] if out.cut else records:
                meta, _, path = record.partition("\t")
                parts = meta.split(" ")
                if len(parts) == 3 and parts[1] == "blob":
                    found.append((parts[2], path))
        return found

    def sync(self) -> str:
        """Bring the mirror up to date with its host — make it on the first call — and say what changed."""
        with self._locked():
            fresh = not self.ready
            work = self.git_dir.with_suffix(".new") if fresh else self.git_dir
            try:
                if fresh:
                    self._make(work)
                default, remote = self._remote_refs(work)
                skipped = self.status().skipped
                wanted = {
                    name: oid for name, oid in remote.items() if self.keeps(name, default) and skipped.get(name) != oid
                }
                local = self._local_refs(work)
                moved = [name for name, oid in wanted.items() if local.get(name) != oid]
                gone = [name for name in local if name not in wanted]
                odd: list[str] = []
                if moved:
                    # `+`: a force-pushed branch (or a moved tag) is followed; `--atomic`: all of them move, or none.
                    refspecs = "".join(f"+{name}:{name}\n" for name in moved)
                    self._git(
                        work,
                        *("fetch", "--quiet", "--atomic", "--no-tags", "--no-write-fetch-head"),
                        *("--recurse-submodules=no", "--filter=blob:none", "--stdin", "origin"),
                        network=True,
                        input=refspecs.encode(),
                        config=IN_SYNC,
                    )
                    # A tag of a tree or of a file's contents is not kept: nothing reads it, and its contents have
                    # no path for include / exclude to judge. (Git sends what a ref names — a tag of a file's contents
                    # brings that one file — so it is dropped once fetched, and remembered so it isn't fetched again;
                    # `--filter` keeps out all the rest.)
                    odd = self._not_commits(work, moved)
                    skipped = {**skipped, **{name: wanted[name] for name in odd}}
                    moved = [name for name in moved if name not in odd]
                    wanted = {name: oid for name, oid in wanted.items() if name not in odd}
                if gone or odd:
                    deletions = "".join(f"delete {name}\n" for name in gone + odd)
                    self._git(work, "update-ref", "--stdin", input=deletions.encode())
                if default in wanted:
                    self._git(work, "symbolic-ref", "HEAD", default)
                tips = [wanted[name] for name in moved] + ([wanted[default]] if default in wanted else [])
                fetched = self.ensure(self._served_at(work, tips), git_dir=work)
                if fresh:
                    os.rename(work, self.git_dir)
            except (SyncError, OSError) as error:
                reason = str(error) if isinstance(error, SyncError) else f"{error.strerror or error}: {self.git_dir}"
                self._record(reason)
                if fresh:
                    shutil.rmtree(work, ignore_errors=True)
                raise SyncError(reason) from None
            self._record(None, {name: oid for name, oid in skipped.items() if remote.get(name) == oid})
        branches = sum(1 for name in wanted if name.startswith("refs/heads/"))
        if fresh:
            kept = f"{_plural(branches, 'branch', 'branches')}, {_plural(len(wanted) - branches, 'tag')}"
            return f"mirrored for the first time — {kept}, {_plural(fetched, 'file')}' contents"
        if not moved and not gone and not fetched:
            return "up to date"
        changes = [f"{_plural(len(moved), 'ref')} moved" if moved else "", f"{len(gone)} dropped" if gone else ""]
        changes.append(f"{_plural(fetched, 'file')}' contents fetched" if fetched else "")
        return ", ".join(change for change in changes if change)

    def reach(self) -> str:
        """For `--check`: whether the host answers, and what the mirror would keep — nothing kept."""
        with tempfile.TemporaryDirectory(prefix="repo-reader-check-") as tmp:
            probe = Path(tmp) / "probe.git"
            self._make(probe)
            default, remote = self._remote_refs(probe)
        kept = [name for name in remote if self.keeps(name, default)]
        branches = sum(1 for name in remote if name.startswith("refs/heads/"))
        kept_branches = sum(1 for name in kept if name.startswith("refs/heads/"))
        return (
            f"reachable: {_plural(branches, 'branch', 'branches')} and {_plural(len(remote) - branches, 'tag')}, "
            f"of which it keeps {kept_branches} and {len(kept) - kept_branches}"
        )

    # --- contents, on purpose -------------------------------------------------------------------------------------

    def ensure(self, wanted: Iterable[tuple[str, str]], *, git_dir: Path | None = None) -> int:
        """Fetch the contents among `wanted` — (object, path) pairs — that the mirror lacks, of served paths only:
        a path outside include / exclude is never fetched, whoever asks. Returns how many were fetched. Asked by a
        tool (no `git_dir`), the fetch is stopped after two minutes: an agent is waiting."""
        where = git_dir or self.git_dir
        oids = sorted(
            {oid for oid, path in wanted if OID.fullmatch(oid) and oid not in NULL and self.config.matcher.allows(path)}
        )
        if not oids:
            return 0
        listing = ("\n".join(oids) + "\n").encode()
        # Lists the objects given that the mirror has, and skips the rest — never fetching them.
        present = self._git(
            where, "rev-list", "--objects", "--no-walk", "--ignore-missing", "--missing=print", "--stdin",
            input=listing, limit=LIST_BYTES,
        )  # fmt: skip
        have = {line.split(" ", 1)[0] for line in present.text.splitlines()}
        missing = [oid for oid in oids if oid not in have]
        if missing:
            self._git(
                where,
                *("fetch", "--quiet", "--no-tags", "--no-write-fetch-head", "--recurse-submodules=no"),
                *("--filter=blob:none", "--stdin", "origin"),
                network=True,
                input=("\n".join(missing) + "\n").encode(),
                config=ON_DEMAND,
                timeout=None if git_dir else ON_DEMAND_TIMEOUT_SECONDS,
            )
        return len(missing)

    # --- status ---------------------------------------------------------------------------------------------------

    def status(self) -> Status:
        try:
            data = json.loads(self.status_file.read_text(encoding="utf-8"))
            skipped = data.get("skipped") or {}
            return Status(data.get("synced"), data.get("failed"), data.get("error"), dict(skipped))
        except (OSError, ValueError, AttributeError, TypeError):
            return Status()

    def _record(self, error: str | None, skipped: dict[str, str] | None = None) -> None:
        """The outcome of a sync, on disk — so every server process sharing the folder can tell it."""
        now = datetime.now(UTC).isoformat(timespec="seconds")
        before = self.status()
        status = {
            "synced": now if error is None else before.synced,
            "failed": now if error else None,
            "error": error,
            "skipped": before.skipped if skipped is None else skipped,
        }
        try:
            self.git_dir.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.status_file.with_suffix(f".{os.getpid()}.tmp")
            temporary.write_text(json.dumps(status), encoding="utf-8")
            os.replace(temporary, self.status_file)
        except OSError as problem:
            log.warning("%s: can't record the sync's status: %s", self.name, problem)

    def describe(self) -> str:
        """A line for agents: where the mirror comes from, how fresh it is, and what went wrong if anything did."""
        status = self.status()
        url = self.remote.url
        if not self.ready:
            if status.error:
                return (
                    f"Mirroring it from {url} failed ({_when(status.failed)}): {status.error} — the server tries again "
                    "at its next sync."
                )
            return f"It is being mirrored from {url} for the first time — ask again in a minute."
        group = f" (one of `{self.config.group}`)" if self.config.group else ""
        line = f"Mirrored from {url}{group}, synced {_when(status.synced)}"
        if status.error:
            line += f"; the last sync failed ({_when(status.failed)}): {status.error}"
        return line + "."


def sync_all(mirrors: list[Mirror]) -> list[tuple[Mirror, str, bool]]:
    """Every mirror synced, a few at a time: each with what changed (or why it failed), and whether it worked."""

    def one(mirror: Mirror) -> tuple[Mirror, str, bool]:
        try:
            return mirror, mirror.sync(), True
        except SyncError as error:
            return mirror, str(error), False

    with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="repo-reader-sync") as pool:
        return list(pool.map(one, mirrors))
