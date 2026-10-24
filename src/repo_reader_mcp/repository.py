"""Reading one repository: refs, trees, files, history, diffs, blame — through `git.run` only.

A ref an agent gives is checked and resolved to a commit id first; every later command gets that id, never the
agent's text. Paths reach git after `--`, read literally.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cached_property

from .config import RepositoryConfig
from .git import GitError, Output, run

HEX = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
EMPTY_TREE = {
    "sha1": "4b825dc642cb6eb9a060e54bf8d69288fbee4904",
    "sha256": "6ef19b41225c5369f1c104d45d8d85efa9b057b53b14b4b9b939dd74decc5321",
}
SEP = "\x1f"
END = "\x1e"


class ReadError(Exception):
    """Something an agent asked for can't be read; the message says why, for the agent."""


def records(out: Output, separator: str) -> list[str]:
    """The complete records of an output: when it was cut, the last record may be partial and is dropped."""
    parts = out.text.split(separator)
    return parts[:-1] if out.cut else parts


def check_ref(ref: str) -> str:
    """A ref as an agent wrote it, refused when it could be taken for anything but a ref."""
    if not ref or len(ref) > 256:
        raise ReadError("a ref is a branch, a tag or a commit id, up to 256 characters")
    if ref.startswith("-"):
        raise ReadError(f"`{ref}` is not a ref: a ref can't start with `-`")
    if any(ord(ch) <= 32 or ord(ch) == 127 for ch in ref):
        raise ReadError("a ref can't contain spaces or control characters")
    return ref


@dataclass(frozen=True)
class At:
    """Where a tool reads: what the agent asked for (or the default branch) and the commit it is."""

    label: str
    commit: str
    date: str

    @property
    def short(self) -> str:
        return self.commit[:12]

    def describe(self) -> str:
        if self.commit.startswith(self.label):
            return f"commit {self.short} ({self.date})"
        return f"{self.label} @ {self.short} ({self.date})"


@dataclass(frozen=True)
class Entry:
    mode: str
    kind: str  # blob, tree, or commit (a submodule)
    oid: str
    path: str

    @property
    def is_link(self) -> bool:
        return self.mode == "120000"


@dataclass(frozen=True)
class Ref:
    name: str
    kind: str  # branch, remote, tag
    commit: str
    date: str
    subject: str


@dataclass(frozen=True)
class LogEntry:
    commit: str
    date: str
    author: str
    subject: str
    paths: tuple[str, ...] = ()  # the files it changed (against its first parent), when asked for


@dataclass(frozen=True)
class CommitInfo:
    commit: str
    parents: list[str]
    author: str
    author_date: str
    committer: str
    committer_date: str
    message: str


@dataclass(frozen=True)
class Change:
    status: str  # A added, M modified, D deleted, T type changed
    path: str
    added: int | None  # None for a binary file
    deleted: int | None


@dataclass(frozen=True)
class BlameLine:
    number: int
    commit: str
    text: str


@dataclass(frozen=True)
class BlameCommit:
    date: str
    author: str
    subject: str


class Repository:
    def __init__(self, config: RepositoryConfig):
        self.config = config
        self.name = config.name
        self.matcher = config.matcher

    def git(self, *args: str, limit: int | None = None, ok_codes: tuple[int, ...] = (0,)) -> Output:
        try:
            return run(self.config.git_dir, args, limit=limit, ok_codes=ok_codes)
        except GitError as error:
            if "promisor" in error.stderr or "transport" in error.stderr:
                raise ReadError(
                    f"the contents are not in {self.name}'s local copy (a partial clone), "
                    "and this server never downloads anything"
                ) from None
            raise ReadError(f"git could not read it: {error}") from None

    # --- refs ---------------------------------------------------------------------------------------------------

    def default_branch(self) -> str | None:
        name = self.git("symbolic-ref", "--quiet", "--short", "HEAD", ok_codes=(0, 1)).text.strip()
        return name or None

    @cached_property
    def object_format(self) -> str:
        return self.git("rev-parse", "--show-object-format").text.strip() or "sha1"

    def resolve(self, ref: str | None) -> At:
        """The commit a ref names; without one, the default branch."""
        if ref is None:
            label = self.default_branch() or "HEAD"
            target = "HEAD"
        else:
            label = target = check_ref(ref)
        found = self.git(
            "rev-parse", "--verify", "--quiet", "--end-of-options", f"{target}^{{commit}}", ok_codes=(0, 1)
        ).text.strip()
        if not HEX.fullmatch(found):
            if ref is None:
                raise ReadError(f"{self.name} has no commits yet")
            raise ReadError(f"{self.name} has no branch, tag or commit `{ref}` — list_refs lists its branches and tags")
        date = self.git("log", "-1", "--format=%cs", found, "--").text.strip()
        return At(label, found, date)

    def refs(self) -> tuple[list[Ref], bool]:
        """Branches, remote-tracking branches and tags, newest first; and whether there were more than were read."""
        fields = [
            "%(refname)",
            "%(objecttype)",
            "%(objectname)",
            "%(*objecttype)",
            "%(*objectname)",
            "%(creatordate:short)",
            "%(symref)",
            "%(subject)",
        ]
        out = self.git(
            "for-each-ref",
            "--sort=-creatordate",
            "--format=" + "%1f".join(fields),
            "refs/heads",
            "refs/remotes",
            "refs/tags",
        )
        refs = []
        for line in records(out, "\n"):
            parts = line.split(SEP)
            if len(parts) != len(fields):
                continue
            refname, kind, oid, peeled_kind, peeled, date, symref, subject = parts
            if symref:
                continue  # origin/HEAD and the like: another name for a branch already listed
            commit = peeled if kind == "tag" else oid
            if (peeled_kind if kind == "tag" else kind) != "commit":
                continue
            for prefix, ref_kind in (("refs/heads/", "branch"), ("refs/remotes/", "remote"), ("refs/tags/", "tag")):
                if refname.startswith(prefix):
                    refs.append(Ref(refname[len(prefix) :], ref_kind, commit, date, subject))
        return refs, out.cut

    def merge_base(self, a: str, b: str) -> str | None:
        found = self.git("merge-base", a, b, ok_codes=(0, 1)).text.strip()
        return found if HEX.fullmatch(found) else None

    # --- trees and files ----------------------------------------------------------------------------------------

    @staticmethod
    def _entries(out: Output) -> list[Entry]:
        entries = []
        for record in records(out, "\0"):
            if not record:
                continue
            meta, _, path = record.partition("\t")
            mode, kind, oid = meta.split(" ")
            entries.append(Entry(mode, kind, oid, path))
        return entries

    def entry(self, at: At, path: str) -> Entry | None:
        """What is at a path in a commit: a file, a folder, a submodule — or None."""
        found = self._entries(self.git("ls-tree", "-z", "--full-tree", at.commit, "--", path))
        return next((e for e in found if e.path == path), None)

    def files(self, at: At, folder: str = "") -> tuple[list[Entry], bool]:
        """Every file (and submodule) under a folder, at any depth, as git has them — before include/exclude; and
        whether the tree held more than was read."""
        out = self.git("ls-tree", "-r", "-z", "--full-tree", at.commit, "--", *([folder] if folder else []))
        return self._entries(out), out.cut

    def children(self, at: At, folder: str = "") -> tuple[list[Entry], bool]:
        """What a folder holds directly — files, folders, submodules — before include/exclude."""
        out = self.git("ls-tree", "-z", "--full-tree", at.commit, "--", *([folder + "/"] if folder else []))
        return self._entries(out), out.cut

    def blob(self, entry: Entry, limit: int) -> Output:
        return self.git("cat-file", "blob", entry.oid, limit=limit)

    # --- history ------------------------------------------------------------------------------------------------

    def log(
        self,
        at: At,
        *,
        path: str | None = None,
        author: str | None = None,
        since: str | None = None,
        until: str | None = None,
        message: str | None = None,
        count: int | None = 30,
        skip: int = 0,
        with_paths: bool = False,
    ) -> tuple[list[LogEntry], bool]:
        """Commits newest first (all of them when `count` is None); and whether there were more than were read.

        `with_paths` adds the files each commit changed — against its first parent, renames as a deletion and an
        addition.
        """
        args = ["log", f"--skip={skip}", *([f"--max-count={count}"] if count is not None else [])]
        if with_paths:
            args += [
                f"--format={END}%H{SEP}%cs{SEP}%an{SEP}%s",
                "--name-only",
                "-z",
                "--no-renames",
                "--diff-merges=first-parent",
            ]
        else:
            args.append(f"--format=%H{SEP}%cs{SEP}%an{SEP}%s{END}")
        if author:
            args.append(f"--author={author}")
        if since:
            args.append(f"--since={since}")
        if until:
            args.append(f"--until={until}")
        if message:
            args.append(f"--grep={message}")
        if author or message:
            args.append("--regexp-ignore-case")
        args += [at.commit, "--", *([path] if path else [])]
        out = self.git(*args)
        entries = []
        for record in records(out, END):
            head, _, names = record.partition("\0") if with_paths else (record, "", "")
            parts = head.strip("\n").split(SEP)
            if len(parts) == 4:
                paths = tuple(name for name in names.lstrip("\n").split("\0") if name)
                entries.append(LogEntry(*parts, paths=paths))
        return entries, out.cut

    def commit(self, at: At) -> CommitInfo:
        out = self.git("log", "-1", f"--format=%H{SEP}%P{SEP}%an{SEP}%aI{SEP}%cn{SEP}%cI{SEP}%B", at.commit, "--").text
        commit, parents, author, author_date, committer, committer_date, message = out.split(SEP, 6)
        return CommitInfo(commit, parents.split(), author, author_date, committer, committer_date, message.strip("\n"))

    def empty_tree(self) -> str:
        return EMPTY_TREE[self.object_format]

    def changes(self, base: str, head: str) -> tuple[list[Change], bool]:
        """The files that differ between two commits (or a tree), renames shown as a deletion and an addition; and
        whether there were more than were read."""
        raw = self.git("diff", "--raw", "-z", "--no-renames", "--no-abbrev", base, head, "--")
        fields = records(raw, "\0")
        statuses = {
            fields[i + 1]: fields[i].split(" ")[-1][:1]
            for i in range(0, len(fields) - 1, 2)
            if fields[i].startswith(":")
        }
        numstat = self.git("diff", "--numstat", "-z", "--no-renames", base, head, "--")
        counts: dict[str, tuple[int | None, int | None]] = {}
        for record in records(numstat, "\0"):
            added, _, rest = record.partition("\t")
            deleted, _, path = rest.partition("\t")
            if path:
                counts[path] = (int(added) if added.isdigit() else None, int(deleted) if deleted.isdigit() else None)
        changes = [Change(status, path, *counts.get(path, (None, None))) for path, status in statuses.items()]
        return changes, raw.cut

    def patch(self, base: str, head: str, paths: list[str] | None, limit: int) -> Output:
        """The diff between two commits for some paths (all, when None), stopped after `limit` bytes."""
        return self.git("diff", "-p", "--no-renames", base, head, "--", *(paths or []), limit=limit)

    def blame(self, at: At, path: str, start: int, end: int) -> tuple[list[BlameLine], dict[str, BlameCommit]]:
        out = self.git("blame", "--porcelain", f"-L{start},{end}", at.commit, "--", path)
        lines: list[BlameLine] = []
        meta: dict[str, dict[str, str]] = {}
        current = ""
        number = 0
        for raw in records(out, "\n"):
            if raw.startswith("\t"):
                lines.append(BlameLine(number, current, raw[1:]))
                continue
            parts = raw.split(" ")
            if len(parts) >= 3 and HEX.fullmatch(parts[0]) and parts[1].isdigit() and parts[2].isdigit():
                current, number = parts[0], int(parts[2])
                meta.setdefault(current, {})
            elif current and raw:
                key, _, value = raw.partition(" ")
                meta[current].setdefault(key, value)
        commits = {}
        for commit, info in meta.items():
            date = _epoch_date(info.get("author-time", ""))
            commits[commit] = BlameCommit(date, info.get("author", ""), info.get("summary", ""))
        return lines, commits


def _epoch_date(value: str) -> str:
    return datetime.fromtimestamp(int(value), UTC).strftime("%Y-%m-%d") if value.isdigit() else ""
