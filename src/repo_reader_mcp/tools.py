"""The reading tools (docs/reference/tools.md): each answers in plain text that names the repository, the ref and the
commit it was read at, sized to `limits.answer_characters`; a cut answer says so and how to go on.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from .config import Config
from .paths import PathError, clean_path, under
from .repository import At, Change, Entry, ReadError, Repository

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False)

FILE_BYTES = 10 * 1024 * 1024  # a file larger than this is not read
BINARY_SNIFF = 8000  # a NUL byte in the first this-many bytes marks a file binary
LINE_CHARACTERS = 2000  # a longer line is cut, saying how much
NOTE_RESERVE = 400  # kept free in every answer for the closing note
PATCH_BATCH = 100  # paths per git call when a diff is limited to some files
BLAME_LINES = 5000  # the most lines one blame call works on

RepoName = Annotated[str, Field(description="A repository's name, as list_repos shows it.")]
RefArg = Annotated[
    str | None,
    Field(description="A branch, tag or commit id (`main`, `v1.2`, `a1b2c3d`, `main~3`). Default: the default branch."),
]
StartLine = Annotated[int, Field(ge=1, description="The first line to show, from 1.")]
MaxLines = Annotated[int | None, Field(ge=1, description="At most this many lines. Default: as many as fit.")]


class Answer:
    """Lines of an answer, kept under the character limit; `full` once a line didn't fit."""

    def __init__(self, limit: int):
        self.room = limit - NOTE_RESERVE
        self.lines: list[str] = []
        self.size = 0
        self.full = False

    def add(self, line: str = "") -> bool:
        if self.full or self.size + len(line) + 1 > self.room:
            self.full = True
            return False
        self.lines.append(line)
        self.size += len(line) + 1
        return True

    @property
    def left(self) -> int:
        return max(self.room - self.size, 0)

    def text(self, note: str | None = None) -> str:
        return "\n".join(self.lines + ([f"\n[{note}]"] if note else [])).rstrip("\n") + "\n"


def _cut_line(line: str) -> str:
    if len(line) <= LINE_CHARACTERS:
        return line
    return f"{line[:LINE_CHARACTERS]} …[{len(line) - LINE_CHARACTERS} more characters]"


def _lines(data: bytes) -> list[str]:
    lines = data.decode("utf-8", errors="replace").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [line.removesuffix("\r") for line in lines]


def _plural(count: int, word: str, many: str | None = None) -> str:
    return f"{count} {word if count == 1 else many or word + 's'}"


def _counts(change: Change) -> str:
    if change.added is None:
        return "binary"
    parts = (f"+{change.added}" if change.added else "", f"−{change.deleted}" if change.deleted else "")
    return " ".join(part for part in parts if part)


def register(server: MCPServer, config: Config) -> None:
    """Add the reading tools over the configured repositories to a server."""
    repositories = {repo.name: Repository(repo) for repo in config.repositories}
    limit = config.limits.answer_characters

    def repo_named(name: str) -> Repository:
        if name in repositories:
            return repositories[name]
        known = ", ".join(sorted(repositories)) or "none are configured"
        raise ToolError(f"no repository named `{name}` — known: {known}")

    def path_of(path: str, *, allow_root: bool = False) -> str:
        try:
            return clean_path(path, allow_root=allow_root)
        except PathError as error:
            raise ToolError(str(error)) from None

    def outside(repo: Repository, path: str) -> ToolError:
        return ToolError(f"`{path}` is outside what this server serves from {repo.name} (its include / exclude)")

    def served_file(repo: Repository, at: At, path: str) -> Entry:
        """The file at a path, refusing what is not served, a folder, a submodule, or nothing."""
        if not repo.matcher.allows(path):
            raise outside(repo, path)
        entry = repo.entry(at, path)
        if entry is None:
            raise ToolError(f"{repo.name} has no file `{path}` at {at.describe()}")
        if entry.kind == "tree":
            raise ToolError(f"`{path}` is a folder at {at.describe()} — list it with list_files")
        if entry.kind == "commit":
            raise ToolError(f"`{path}` is a submodule (another repository, at commit {entry.oid[:12]}), not a file")
        return entry

    def served_files(repo: Repository, at: At, folder: str) -> tuple[list[Entry], bool]:
        found, cut = repo.files(at, folder)
        return [e for e in found if repo.matcher.allows(e.path)], cut

    def scope(repo: Repository, at: At, path: str | None) -> str | None:
        """The file or folder a history or a diff is narrowed to — refused when nothing in it is served, judged by
        the path alone (at `at`), so the answer never tells whether something unseen changed."""
        clean = path_of(path, allow_root=True) if path else ""
        if not clean:
            return None
        entry = repo.entry(at, clean)
        if entry is not None and entry.kind == "tree":
            if not served_files(repo, at, clean)[0]:
                raise outside(repo, clean)
        elif not repo.matcher.allows(clean):
            raise outside(repo, clean)
        return clean

    def guard(fn):
        """Turn a ReadError into the tool error an agent reads."""

        def wrapped(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except ReadError as error:
                raise ToolError(str(error)) from None

        wrapped.__name__ = fn.__name__
        wrapped.__doc__ = fn.__doc__
        wrapped.__annotations__ = fn.__annotations__
        wrapped.__wrapped__ = fn
        return wrapped

    def tool(fn):
        server.add_tool(guard(fn), annotations=READ_ONLY, structured_output=False)
        return fn

    # --- list_repos -----------------------------------------------------------------------------------------------

    @tool
    def list_repos() -> str:
        """The repositories this server reads: each one's default branch and the commit it is at, its branches and
        tags, and what of it is served. Call it first; the other tools take a repository's name as `repo`."""
        answer = Answer(limit)
        if not repositories:
            return "No repositories are configured on this server.\n"
        count = _plural(len(repositories), "repository", "repositories")
        answer.add(f"{count} — read-only. Name one as `repo` in the other tools.")
        for repo in repositories.values():
            answer.add()
            answer.add(f"## {repo.name}")
            if repo.config.description:
                answer.add(repo.config.description.strip())
            try:
                at = repo.resolve(None)
            except ReadError as error:
                answer.add(str(error))
                continue
            latest, _ = repo.log(at, count=1)
            answer.add(f"Default branch: {at.describe()} — {latest[0].subject if latest else ''}")
            refs, _ = repo.refs()
            branches = sum(1 for r in refs if r.kind == "branch")
            remotes = sum(1 for r in refs if r.kind == "remote")
            tags = sum(1 for r in refs if r.kind == "tag")
            line = f"{_plural(branches, 'branch', 'branches')}, {_plural(tags, 'tag')}"
            if remotes:
                line += f", {remotes} remote-tracking"
            answer.add(line + " — list_refs lists them")
            if not repo.matcher.takes_everything:
                answer.add("Serves only part of it: paths outside its include / exclude are not shown.")
        return answer.text("cut: more repositories than fit" if answer.full else None)

    # --- list_refs ------------------------------------------------------------------------------------------------

    @tool
    def list_refs(
        repo: RepoName,
        kind: Annotated[
            Literal["all", "branches", "tags"], Field(description="Branches (with remote-tracking), tags, or all.")
        ] = "all",
        pattern: Annotated[
            str | None, Field(description="Only names matching this glob, like `release/*` or `v1.*`.")
        ] = None,
    ) -> str:
        """Branches and tags of a repository, newest first: the commit each points at, its date and subject. Any of
        them — or any commit id — can be passed as `ref` to the reading tools."""
        r = repo_named(repo)
        default = r.default_branch()
        found, unread = r.refs()
        refs = [ref for ref in found if not pattern or fnmatchcase(ref.name, pattern)]
        groups = {"branch": "Branches", "remote": "Remote-tracking branches", "tag": "Tags"}
        wanted = {"all": groups, "branches": ("branch", "remote"), "tags": ("tag",)}[kind]
        shown = [ref for ref in refs if ref.kind in wanted]
        answer = Answer(limit)
        filters = f" matching `{pattern}`" if pattern else ""
        answer.add(f"{r.name} — {_plural(len(shown), 'ref')}{filters}, newest first. `*` marks the default branch.")
        width = min(max((len(ref.name) for ref in shown), default=0), 40)
        hidden = 0
        for group, title in groups.items():
            members = [ref for ref in shown if ref.kind == group]
            if not members or answer.full:
                hidden += len(members) if answer.full else 0
                continue
            answer.add()
            answer.add(f"{title}:")
            for ref in members:
                mark = "*" if group == "branch" and ref.name == default else " "
                if not answer.add(f"{mark} {ref.name:<{width}}  {ref.commit[:12]}  {ref.date}  {ref.subject}"):
                    hidden += 1
        if hidden or unread:
            more = f"{hidden} more not shown" if hidden else "the repository has more refs than are read at once"
            return answer.text(f"cut: {more} — narrow with `pattern` or `kind`")
        return answer.text()

    # --- read_file ------------------------------------------------------------------------------------------------

    @tool
    def read_file(
        repo: RepoName,
        path: Annotated[str, Field(description="The file, from the repository's root: `src/app.py`.")],
        ref: RefArg = None,
        start_line: StartLine = 1,
        max_lines: MaxLines = None,
    ) -> str:
        """A file at any branch, tag or commit, as numbered lines — a window at a time: a long file is cut where the
        answer is full, and the answer says which `start_line` continues it."""
        r = repo_named(repo)
        clean = path_of(path)
        at = r.resolve(ref)
        entry = served_file(r, at, clean)
        data = r.blob(entry, FILE_BYTES)
        head = f"{r.name} · {clean} · {at.describe()}"
        if data.cut:
            raise ToolError(f"`{clean}` is larger than {FILE_BYTES // (1024 * 1024)} MB — too large to read")
        if entry.is_link:
            return f"{head}\n\nA symbolic link to `{data.text}` — not followed; read the target by its own path.\n"
        if b"\0" in data.data[:BINARY_SNIFF]:
            return f"{head}\n\nA binary file of {len(data.data)} bytes — not shown.\n"
        lines = _lines(data.data)
        total = len(lines)
        if total == 0:
            return f"{head} · empty\n"
        if start_line > total:
            raise ToolError(f"`{clean}` has {_plural(total, 'line')} at {at.describe()}; start_line is past its end")
        last = total if max_lines is None else min(total, start_line + max_lines - 1)
        width = len(str(last))
        body = Answer(limit - len(head) - 60)
        shown_to = start_line - 1
        for number in range(start_line, last + 1):
            if not body.add(f"{number:>{width}}\t{_cut_line(lines[number - 1])}"):
                break
            shown_to = number
        if shown_to < start_line:
            raise ToolError(f"line {start_line} alone is longer than the answer limit")
        note = None
        if shown_to < total:
            more = "the answer is full" if body.full else "as asked"
            note = f"lines {shown_to + 1}–{total} not shown ({more}) — call read_file with start_line={shown_to + 1}"
        span = f"lines {start_line}–{shown_to} of {total}"
        return f"{head} · {span}\n\n" + body.text(note)

    # --- list_files -----------------------------------------------------------------------------------------------

    @tool
    def list_files(
        repo: RepoName,
        path: Annotated[str, Field(description="A folder from the repository's root; empty for the root.")] = "",
        ref: RefArg = None,
        recursive: Annotated[bool, Field(description="Every file under the folder, at any depth.")] = False,
    ) -> str:
        """A folder at any branch, tag or commit: its subfolders (ending in `/`) and files, with full paths from the
        root. `recursive` lists every file under it instead."""
        r = repo_named(repo)
        folder = path_of(path, allow_root=True)
        at = r.resolve(ref)
        where = f"{folder}/" if folder else "the root"
        prefix = f"{folder}/" if folder else ""
        folders: list[str] = []
        if not recursive and r.matcher.takes_everything:
            # Nothing is held back, so git lists the folder's own entries without walking the tree under it.
            entries, cut = r.children(at, folder)
            folders = sorted(e.path + "/" for e in entries if e.kind == "tree")
            files = [e for e in entries if e.kind != "tree"]
        else:
            found, cut = served_files(r, at, folder)
            files = [f for f in found if under(f.path, folder) and f.path != folder]
            if not recursive:
                inner = [f.path[len(prefix) :] for f in files]
                folders = sorted({prefix + rest.split("/", 1)[0] + "/" for rest in inner if "/" in rest})
                files = [f for f in files if "/" not in f.path[len(prefix) :]]
        if not folders and not files:
            entry = r.entry(at, folder) if folder else None
            if entry is not None and entry.kind != "tree" and r.matcher.allows(folder):
                raise ToolError(f"`{folder}` is a file — read it with read_file")
            raise ToolError(f"{r.name} has no files this server serves under {where} at {at.describe()}")

        def label(e: Entry) -> str:
            return e.path + (" (submodule)" if e.kind == "commit" else " (link)" if e.is_link else "")

        items = folders + [label(f) for f in sorted(files, key=lambda e: e.path)]
        if recursive:
            summary = _plural(len(files), "file")
        else:
            summary = f"{_plural(len(folders), 'folder')}, {_plural(len(files), 'file')}"
        answer = Answer(limit)
        answer.add(f"{r.name} · {where} · {at.describe()} — {summary}")
        answer.add()
        shown = sum(1 for item in items if answer.add(item))
        note = None
        if cut:
            note = "cut: the folder holds more than the server reads at once, so not all is shown — narrow with `path`"
        elif shown < len(items):
            note = f"cut: {len(items) - shown} more not shown — list a subfolder with `path`"
        return answer.text(note)

    # --- log ------------------------------------------------------------------------------------------------------

    @tool
    def log(
        repo: RepoName,
        ref: RefArg = None,
        path: Annotated[str | None, Field(description="Only commits that changed this file or folder.")] = None,
        author: Annotated[str | None, Field(description="Only commits whose author's name or email matches.")] = None,
        message: Annotated[str | None, Field(description="Only commits whose message matches (a regex).")] = None,
        since: Annotated[str | None, Field(description="Only commits after: `2026-01-31`, `2 weeks ago`.")] = None,
        until: Annotated[str | None, Field(description="Only commits before this date.")] = None,
        max_count: Annotated[int, Field(ge=1, le=500, description="At most this many commits.")] = 30,
        skip: Annotated[int, Field(ge=0, description="Skip this many first — to page on.")] = 0,
    ) -> str:
        """The history of a branch, tag or commit — of the whole repository or one path — newest first: each
        commit's id, date, author and subject. Read one with show_commit."""
        r = repo_named(repo)
        at = r.resolve(ref)
        clean = scope(r, at, path)
        commits, unread = r.log(
            at, path=clean, author=author, since=since, until=until, message=message, count=max_count + 1, skip=skip
        )
        more = len(commits) > max_count or unread
        commits = commits[:max_count]
        filters = [f"of {clean}" if clean else ""]
        filters += [
            f"{key} `{value}`"
            for key, value in (("by", author), ("message", message), ("since", since), ("until", until))
            if value
        ]
        title = " ".join(f for f in filters if f)
        answer = Answer(limit)
        answer.add(f"{r.name} · log{' ' + title if title else ''} · {at.describe()} — newest first")
        answer.add()
        if not commits:
            answer.add("No commits match.")
        shown = 0
        for c in commits:
            if not answer.add(f"{c.commit[:12]}  {c.date}  {c.author}  {c.subject}"):
                break
            shown += 1
        note = None
        if shown < len(commits) or more:
            note = f"more commits: call log with skip={skip + shown}"
        return answer.text(note)

    # --- show_commit and diff -------------------------------------------------------------------------------------

    def changes_answer(r: Repository, answer: Answer, base: str, head: str, path: str | None, files_only: bool) -> str:
        changes, unread = r.changes(base, head)
        scoped = [c for c in changes if path is None or under(c.path, path)]
        served = [c for c in scoped if r.matcher.allows(c.path)]
        hidden = len(scoped) - len(served)
        added = sum(c.added or 0 for c in served)
        deleted = sum(c.deleted or 0 for c in served)
        scope = f" under {path}" if path else ""
        if not served:
            unseen = f" in what this server serves ({_plural(hidden, 'file')} not shown)" if hidden else ""
            answer.add(f"No changes{scope}{unseen}.")
            return answer.text()
        answer.add(f"{_plural(len(served), 'file')} changed{scope}, +{added} −{deleted}:")
        listed = 0
        for c in served:
            if not answer.add(f"  {c.status}  {c.path}  {_counts(c)}".rstrip()):
                break
            listed += 1
        if hidden:
            answer.add(f"({_plural(hidden, 'file')} outside what this server serves not shown.)")
        if listed < len(served):
            return answer.text(f"cut: {len(served) - listed} more files not listed — narrow with `path`")
        if unread:
            return answer.text("cut: more files changed than the server reads at once — narrow with `path`")
        if files_only:
            return answer.text()
        answer.add()
        whole = path is None and r.matcher.takes_everything
        batches = (
            [None]
            if whole
            else [[c.path for c in served[i : i + PATCH_BATCH]] for i in range(0, len(served), PATCH_BATCH)]
        )
        for batch in batches:
            out = r.patch(base, head, batch, answer.left)
            for line in _lines(out.data):
                if not answer.add(_cut_line(line)):
                    break
            if out.cut or answer.full:
                return answer.text("cut: the diff is longer than the answer — narrow with `path`, or files_only=true")
        return answer.text()

    @tool
    def show_commit(
        repo: RepoName,
        commit: Annotated[str, Field(description="A commit id (or any ref: the commit it points at).")],
        path: Annotated[str | None, Field(description="Only the changes under this file or folder.")] = None,
        files_only: Annotated[bool, Field(description="Only the list of changed files, no diff.")] = False,
    ) -> str:
        """One commit: its message, author and dates, parents, the files it changed with lines added and removed, and
        its diff (against the first parent for a merge). A long diff is cut; `path` narrows it."""
        r = repo_named(repo)
        at = r.resolve(commit)
        clean = scope(r, at, path)
        info = r.commit(at)
        answer = Answer(limit)
        answer.add(f"{r.name} · commit {info.commit[:12]}")
        answer.add(f"Author: {info.author}, {info.author_date}")
        if (info.committer, info.committer_date) != (info.author, info.author_date):
            answer.add(f"Committed by: {info.committer}, {info.committer_date}")
        if not info.parents:
            answer.add("Parents: none — the first commit; its changes are everything it adds")
        elif len(info.parents) == 1:
            answer.add(f"Parent: {info.parents[0][:12]}")
        else:
            parents = " ".join(p[:12] for p in info.parents)
            answer.add(f"Parents: {parents} — a merge; the changes below are against the first parent")
        answer.add()
        for line in info.message.split("\n"):
            answer.add(f"    {line}".rstrip())
        answer.add()
        base = info.parents[0] if info.parents else r.empty_tree()
        return changes_answer(r, answer, base, info.commit, clean, files_only)

    @tool
    def diff(
        repo: RepoName,
        base: Annotated[str, Field(description="The ref to compare from: a branch, tag or commit.")],
        head: RefArg = None,
        path: Annotated[str | None, Field(description="Only the changes under this file or folder.")] = None,
        since_fork: Annotated[
            bool,
            Field(description="Compare from where `head` forked off `base` (their merge base): what `head` changed."),
        ] = False,
        files_only: Annotated[bool, Field(description="Only the list of changed files, no diff.")] = False,
    ) -> str:
        """The difference between two refs — branches, tags or commits — as files changed and a diff. With
        `since_fork`, only what `head` changed since it forked off `base` (what a pull request would show)."""
        r = repo_named(repo)
        at_base = r.resolve(base)
        at_head = r.resolve(head)
        clean = scope(r, at_head, path)
        start = at_base.commit
        answer = Answer(limit)
        line = f"{r.name} · diff {at_base.describe()} → {at_head.describe()}"
        if since_fork:
            fork = r.merge_base(at_base.commit, at_head.commit)
            if fork is None:
                raise ToolError(f"`{base}` and `{at_head.label}` share no history in {r.name}")
            start = fork
            line += f" · from their merge base {fork[:12]}"
        answer.add(line)
        answer.add()
        return changes_answer(r, answer, start, at_head.commit, clean, files_only)

    # --- blame ----------------------------------------------------------------------------------------------------

    @tool
    def blame(
        repo: RepoName,
        path: Annotated[str, Field(description="The file, from the repository's root.")],
        ref: RefArg = None,
        start_line: StartLine = 1,
        max_lines: MaxLines = None,
    ) -> str:
        """Who last changed each line of a file at a ref, and in which commit: lines grouped under the commit that
        wrote them (its id, date, author and subject). A window at a time, like read_file."""
        r = repo_named(repo)
        clean = path_of(path)
        at = r.resolve(ref)
        entry = served_file(r, at, clean)
        data = r.blob(entry, FILE_BYTES)
        if data.cut:
            raise ToolError(f"`{clean}` is larger than {FILE_BYTES // (1024 * 1024)} MB — too large to blame")
        if entry.is_link or b"\0" in data.data[:BINARY_SNIFF]:
            raise ToolError(f"`{clean}` is a {'link' if entry.is_link else 'binary file'} — blame reads text files")
        total = len(_lines(data.data))
        if total == 0:
            return f"{r.name} · blame {clean} · {at.describe()} · empty\n"
        if start_line > total:
            raise ToolError(f"`{clean}` has {_plural(total, 'line')} at {at.describe()}; start_line is past its end")
        last = min(total, start_line + (max_lines or BLAME_LINES) - 1)
        lines, commits = r.blame(at, clean, start_line, last)
        width = len(str(last))
        head = f"{r.name} · blame {clean} · {at.describe()}"
        body = Answer(limit - len(head) - 60)
        shown_to = start_line - 1
        current = None
        for line in lines:
            block = []
            if line.commit != current:
                c = commits[line.commit]
                block.append(f"{line.commit[:12]} {c.date} {c.author} — {c.subject}")
            block.append(f"{line.number:>{width}}\t{_cut_line(line.text)}")
            if body.size + sum(len(b) + 1 for b in block) > body.room:
                body.full = True
                break
            for b in block:
                body.add(b)
            current = line.commit
            shown_to = line.number
        note = None
        if shown_to < total:
            more = "the answer is full" if body.full else "as asked" if max_lines else "a window at a time"
            note = f"lines {shown_to + 1}–{total} not shown ({more}) — call blame with start_line={shown_to + 1}"
        return f"{head} · lines {start_line}–{shown_to} of {total}\n\n" + body.text(note)
