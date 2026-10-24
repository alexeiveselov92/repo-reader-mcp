"""Reading one repository: refs, trees, files, history, diffs, blame — through `git.run` only.

A ref an agent gives is checked and resolved to a commit id first; every later command gets that id, never the
agent's text. Paths reach git after `--`, read literally.

A mirrored repository is read the same way; before a command that needs file contents, the contents it lacks are
fetched on purpose (`Mirror.ensure`, served paths only) — the reading commands themselves never reach a host.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import cached_property

from .config import RepositoryConfig
from .git import OID as HEX
from .git import GitError, Output, run
from .mirror import Mirror, SyncError

BATCH = 100  # paths per git call when a command is limited to some files
BLAME_HOPS = 8  # renames with changes blame is helped through on a mirror
SUBMODULE = "160000"
EMPTY_TREE = {
    "sha1": "4b825dc642cb6eb9a060e54bf8d69288fbee4904",
    "sha256": "6ef19b41225c5369f1c104d45d8d85efa9b057b53b14b4b9b939dd74decc5321",
}
SEP = "\x1f"
END = "\x1e"


class ReadError(Exception):
    """Something an agent asked for can't be read; the message says why, for the agent."""


class MissingContents(ReadError):
    """Git needed file contents the repository's copy doesn't hold, and was not allowed to fetch them."""


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
    added: int | None = None  # None for a binary file, or before the lines are counted
    deleted: int | None = None
    contents: tuple[tuple[str, str], ...] = ()  # (object, path) of the file on each side — what a diff of it reads


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
        self.mirror = Mirror(config) if config.remote else None

    def git(self, *args: str, limit: int | None = None, ok_codes: tuple[int, ...] = (0,)) -> Output:
        if self.mirror is not None and not self.mirror.ready:
            raise ReadError(f"{self.name} can't be read yet. {self.mirror.describe()}")
        try:
            return run(self.config.git_dir, args, limit=limit, ok_codes=ok_codes)
        except GitError as error:
            if "promisor" in error.stderr or "transport" in error.stderr:
                if self.mirror is not None:
                    raise MissingContents(
                        f"git needs file contents {self.name}'s mirror doesn't hold, and reading never fetches them"
                    ) from None
                raise MissingContents(
                    f"the contents are not in {self.name}'s local copy (a partial clone), "
                    "and this server never downloads anything"
                ) from None
            raise ReadError(f"git could not read it: {error}") from None

    def ensure(self, contents: list[tuple[str, str]]) -> None:
        """Before a command reads file contents — (object, path) pairs — a mirror fetches those it lacks, of served
        paths only; a local repository has what it has."""
        if self.mirror is None or not contents:
            return
        try:
            self.mirror.ensure(contents)
        except SyncError as error:
            raise ReadError(f"the contents could not be fetched from {self.name}'s host: {error}") from None

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
        try:
            found = self.git(
                "rev-parse", "--verify", "--quiet", "--end-of-options", f"{target}^{{commit}}", ok_codes=(0, 1)
            ).text.strip()
        except MissingContents:
            # The id of something the copy lacks — a file's contents. Answered as any unknown name is: otherwise the
            # answer would tell an agent that contents it guessed (a file's id is its contents' digest) are there.
            found = ""
        if not HEX.fullmatch(found):
            if ref is None:
                raise ReadError(f"{self.name} has no commits yet")
            kept = " (its mirror keeps the branches and tags the server's configuration names)" if self.mirror else ""
            raise ReadError(
                f"{self.name} has no branch, tag or commit `{ref}`{kept} — list_refs lists its branches and tags"
            )
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
        self.ensure([(entry.oid, entry.path)])
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
        author_date, committer_date = _iso(author_date), _iso(committer_date)
        return CommitInfo(commit, parents.split(), author, author_date, committer, committer_date, message.strip("\n"))

    def empty_tree(self) -> str:
        return EMPTY_TREE[self.object_format]

    def changes(self, base: str, head: str) -> tuple[list[Change], bool]:
        """The files that differ between two commits (or a tree), renames shown as a deletion and an addition — their
        lines not counted yet (`count_lines`); and whether there were more than were read. Reads no file contents."""
        raw = self.git("diff", "--raw", "-z", "--no-renames", "--no-abbrev", base, head, "--")
        fields = records(raw, "\0")
        changes = []
        for i in range(0, len(fields) - 1, 2):
            if not fields[i].startswith(":"):
                continue
            old_mode, new_mode, old, new, status = fields[i].lstrip(":").split(" ")
            path = fields[i + 1]
            sides = ((old_mode, old), (new_mode, new))
            contents = tuple((oid, path) for mode, oid in sides if mode not in ("000000", SUBMODULE))
            changes.append(Change(status[:1], path, contents=contents))
        return changes, raw.cut

    def _contents(self, changes: list[Change]) -> list[tuple[str, str]]:
        return [pair for change in changes for pair in change.contents]

    def count_lines(self, base: str, head: str, changes: list[Change], *, whole: bool) -> list[Change]:
        """The changes with the lines each added and removed — read for these files only (for every changed file in
        one call when `whole`: the changes are all there are)."""
        self.ensure(self._contents(changes))
        batches = [None] if whole else [changes[i : i + BATCH] for i in range(0, len(changes), BATCH)]
        counts: dict[str, tuple[int | None, int | None]] = {}
        for batch in batches:
            paths = [c.path for c in batch] if batch is not None else []
            if batch is not None and not paths:
                continue
            numstat = self.git("diff", "--numstat", "-z", "--no-renames", base, head, "--", *paths)
            for record in records(numstat, "\0"):
                added, _, rest = record.partition("\t")
                deleted, _, path = rest.partition("\t")
                if path:
                    counts[path] = (
                        int(added) if added.isdigit() else None,
                        int(deleted) if deleted.isdigit() else None,
                    )
        return [
            replace(c, added=counts.get(c.path, (None, None))[0], deleted=counts.get(c.path, (None, None))[1])
            for c in changes
        ]

    def patch(self, base: str, head: str, changes: list[Change], limit: int, *, whole: bool = False) -> Output:
        """The diff between two commits for these changed files (every changed file when `whole`), stopped after
        `limit` bytes. A file's section comes only for the files asked for: git takes a path as a folder too, so
        `config` would also bring `config/prod.env` where a file was replaced by a folder."""
        self.ensure(self._contents(changes))
        paths = [] if whole else [c.path for c in changes]
        out = self.git("diff", "-p", "--no-renames", base, head, "--", *paths, limit=limit)
        if whole:
            return out
        asked = {f"diff --git {_quoted('a/' + p)} {_quoted('b/' + p)}".encode() for p in paths}
        kept, keep = [], False
        for line in out.data.split(b"\n"):
            if line.startswith(b"diff --git "):
                keep = line in asked
            if keep:
                kept.append(line)
        return Output(b"\n".join(kept), out.cut)

    def _all_lines_at(self, at: At, path: str, start: int, end: int) -> list[BlameLine]:
        entry = self.entry(at, path)
        text = self.blob(entry, 10 * 1024 * 1024).text.split("\n") if entry else []
        return [BlameLine(n, at.commit, text[n - 1].removesuffix("\r")) for n in range(start, min(end, len(text)) + 1)]

    def _blame_commit(self, commit: str) -> dict[str, BlameCommit]:
        author, date, subject = (
            self.git("log", "-1", f"--format=%an{SEP}%cs{SEP}%s", commit, "--").text.strip().split(SEP, 2)
        )
        return {commit: BlameCommit(date, author, subject)}

    def _raw(self, out: Output) -> list[tuple[str, str, str, str, str, str, list[str]]]:
        """`log --raw -z --format=%x01%H` read back: (commit, old mode, new mode, old object, new object, status,
        paths)."""
        fields = records(out, "\0")
        found, commit, i = [], "", 0
        while i < len(fields):
            field = fields[i].strip("\n")
            i += 1
            if field.startswith("\x01"):
                commit = field[1:]
            elif field.startswith(":"):
                old_mode, new_mode, old, new, status = field[1:].split(" ")
                names = fields[i : i + (2 if status[:1] in "RC" else 1)]
                i += len(names)
                found.append((commit, old_mode, new_mode, old, new, status, names))
        return found

    def _chain(self, commit: str, path: str) -> tuple[list[tuple[str, str]], tuple[str, str] | None]:
        """A file's history back from a commit, following moves without changes (git finds them by object, reading
        nothing): every version of it, as (object, path); and where it appeared (the commit, the name it had then)."""
        out = self.git("log", "--follow", "-M100%", "--raw", "-z", "--no-abbrev", "--format=%x01%H", commit, "--", path)
        versions, appeared = [], None
        for at, old_mode, new_mode, old, new, status, names in self._raw(out):
            if old_mode != SUBMODULE:
                versions.append((old, names[0]))
            if new_mode != SUBMODULE:
                versions.append((new, names[-1]))
            if status[:1] == "A" and appeared is None:
                appeared = (at, names[-1])
        return [(oid, name) for oid, name in versions if HEX.fullmatch(oid) and set(oid) != {"0"}], appeared

    def _deleted_in(self, commit: str) -> list[tuple[str, str]]:
        """The files a commit deleted, against its first parent, as (object, path)."""
        out = self.git("diff", "--raw", "-z", "--no-renames", "--no-abbrev", f"{commit}^", commit, "--")
        fields = records(out, "\0")
        return [
            (fields[i].split(" ")[2], fields[i + 1])
            for i in range(0, len(fields) - 1, 2)
            if fields[i].startswith(":") and fields[i].endswith(" D") and not fields[i].startswith(f":{SUBMODULE}")
        ]

    def _renamed_from(self, commit: str, path: str) -> str | None:
        """The file a commit renamed (with changes) into `path`, by git's own comparison — once the contents it compares
        are there."""
        out = self.git("log", "-1", "--follow", "--raw", "-z", "--no-abbrev", "--format=%x01%H", commit, "--", path)
        for _, _, _, _, _, status, names in self._raw(out):
            if status[:1] == "R" and names[-1] == path:
                return names[0]
        return None

    def _blame_on_mirror(self, args: list[str], at: At, path: str) -> tuple[Output | None, str | None]:
        """Blame on a mirror: the file's history fetched first, then — where git, following a rename with changes,
        compares the file with the files deleted beside it — those files and their own history too, as long as they
        are served. Returns git's output; or, where the mirror can't go further, the commit blame must stop at."""
        start = (at.commit, path)
        for _ in range(BLAME_HOPS):
            versions, appeared = self._chain(*start)
            self.ensure(versions)
            try:
                return self.git(*args, at.commit, "--", path), None
            except MissingContents:
                if appeared is None:
                    raise
            commit, name = appeared
            try:
                deleted = self._deleted_in(commit)
            except ReadError:  # a first commit: there is nothing before it to follow
                return None, commit
            if not deleted or not all(self.matcher.allows(p) for _, p in deleted):
                return None, commit
            self.ensure(deleted)
            source = self._renamed_from(commit, name)
            if source is not None:
                start = (f"{commit}^", source)
        return None, appeared[0] if appeared else None

    def blame(
        self, at: At, path: str, start: int, end: int
    ) -> tuple[list[BlameLine], dict[str, BlameCommit], str | None]:
        """Each line's last change; and, on a mirror that can't go further back, the commit blame stopped at."""
        args = ["blame", "--porcelain", f"-L{start},{end}"]
        stopped = None
        if self.mirror is None:
            out = self.git(*args, at.commit, "--", path)
        else:
            out, stopped = self._blame_on_mirror(args, at, path)
            if out is None:
                if stopped is None:
                    raise MissingContents(f"blame needs file contents {self.name}'s mirror doesn't hold")
                if stopped == at.commit:  # the file got its path in the very commit read
                    return self._all_lines_at(at, path, start, end), self._blame_commit(stopped), stopped
                out = self.git(*args, f"{stopped}..{at.commit}", "--", path)
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
        return lines, commits, stopped


ESCAPES = {7: "\\a", 8: "\\b", 9: "\\t", 10: "\\n", 11: "\\v", 12: "\\f", 13: "\\r", 0x22: '\\"', 0x5C: "\\\\"}


def _quoted(path: str) -> str:
    """A path as git writes it in a diff's header: in quotes, escaped, when it holds a quote, a backslash, a control
    character or a byte outside ASCII."""
    raw = path.encode("utf-8", errors="surrogateescape")
    if not any(b < 0x20 or b >= 0x7F or b in (0x22, 0x5C) for b in raw):
        return path
    return '"' + "".join(ESCAPES.get(b) or (f"\\{b:03o}" if b < 0x20 or b >= 0x7F else chr(b)) for b in raw) + '"'


def _iso(value: str) -> str:
    """A date as git's `%aI` / `%cI` gives it, the same whatever git's version (newer ones write UTC as `Z`)."""
    try:
        return datetime.fromisoformat(value).isoformat()
    except ValueError:
        return value


def _epoch_date(value: str) -> str:
    return datetime.fromtimestamp(int(value), UTC).strftime("%Y-%m-%d") if value.isdigit() else ""
