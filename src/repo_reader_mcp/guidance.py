"""Repositories' guidance for agents (docs/reference/guidance.md): what the people who own a repository — and those who
run this server — wrote for agents working with it, delivered as instructions rather than as one more file.

Found by the conventions agents' clients use, always on a repository's default branch (never on the ref an agent
reads: text handed to an agent as instructions can steer it, and any branch can be pushed by anyone with access):

- `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.github/copilot-instructions.md` at the root — always in force;
- `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` in a folder — in force under that folder;
- `.claude/rules/**/*.md` — in force everywhere, or under the patterns of its `paths:`;
- `.cursor/rules/**/*.mdc` — in force everywhere (`alwaysApply: true`), under its `globs:`, or read when needed;
- `.claude/skills/*/SKILL.md` — skills: named and described, read when needed.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

import yaml

from .config import Config, GuidanceSource, RepositoryConfig, TextDoc
from .paths import Matcher, compile_pattern
from .repository import At, Entry, ReadError, Repository

DOC_BYTES = 200 * 1024  # a guidance file is read up to this size

ROOT_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md", ".github/copilot-instructions.md")
FOLDER_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")
CLAUDE_RULE = re.compile(r"\.claude/rules/(?:.+/)?[^/]+\.md")
CURSOR_RULE = re.compile(r"\.cursor/rules/(?:.+/)?[^/]+\.mdc?")
SKILL = re.compile(r"\.claude/skills/([^/]+)/SKILL\.md")

ALWAYS = "always"  # in force for the whole repository
SCOPED = "scoped"  # in force under some paths
WHEN_NEEDED = "when needed"  # named and described; read when it fits the task


@dataclass(frozen=True)
class Doc:
    """One piece of guidance."""

    name: str  # how read_guidance names it
    source: str  # where it was read, for the agent
    text: str
    kind: str
    scope: tuple[str, ...] = ()  # patterns of the paths it applies to, in the repository it guides
    description: str = ""

    def applies_to(self, path: str) -> bool:
        return self.kind == SCOPED and Matcher(include=self.scope).allows(path)


@dataclass
class Guidance:
    docs: list[Doc] = field(default_factory=list)

    def of_kind(self, kind: str) -> list[Doc]:
        return [doc for doc in self.docs if doc.kind == kind]

    def named(self, name: str) -> Doc | None:
        return next((doc for doc in self.docs if name in (doc.name, doc.name.removeprefix("skill "))), None)


def frontmatter(text: str) -> tuple[dict, str]:
    """A markdown file's YAML frontmatter (between `---` lines at its top), and the rest."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, text
    try:
        meta = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError:
        return {}, text
    return (meta if isinstance(meta, dict) else {}), "\n".join(lines[end + 1 :]).lstrip("\n")


def _patterns(value: object) -> tuple[str, ...]:
    """`paths:` / `globs:` as a list or a comma-separated string; patterns that can't be read are left out."""
    items = value if isinstance(value, list) else str(value or "").split(",")
    out = []
    for item in items:
        pattern = str(item).strip()
        try:
            compile_pattern(pattern)
        except ValueError:
            continue
        out.append(pattern)
    return tuple(out)


def is_guidance(relative: str) -> bool:
    """Whether a path (from the root a repository's — or a `from` folder's — guidance is read at) is guidance."""
    if relative in ROOT_FILES:
        return True
    if relative.rsplit("/", 1)[-1] in FOLDER_FILES and not relative.startswith("."):
        return True
    return bool(CLAUDE_RULE.fullmatch(relative) or CURSOR_RULE.fullmatch(relative) or SKILL.fullmatch(relative))


def _doc(name: str, source: str, relative: str, text: str) -> Doc | None:
    """The guidance a convention file gives, from its path and its frontmatter."""
    if relative in ROOT_FILES:
        return Doc(name, source, text, ALWAYS)
    if relative.rsplit("/", 1)[-1] in FOLDER_FILES:
        folder = relative.rsplit("/", 1)[0]
        return Doc(name, source, text, SCOPED, ("/" + folder,))
    meta, body = frontmatter(text)
    description = str(meta.get("description") or "").strip()
    if skill := SKILL.fullmatch(relative):
        title = str(meta.get("name") or skill.group(1)).strip()
        return Doc(f"skill {title}", source, body, WHEN_NEEDED, description=description)
    if CLAUDE_RULE.fullmatch(relative):
        scope = _patterns(meta.get("paths"))
        return Doc(name, source, body, SCOPED if scope else ALWAYS, scope, description)
    if CURSOR_RULE.fullmatch(relative):
        if meta.get("alwaysApply") is True:
            return Doc(name, source, body, ALWAYS, description=description)
        scope = _patterns(meta.get("globs"))
        if scope:
            return Doc(name, source, body, SCOPED, scope, description)
        return Doc(name, source, body, WHEN_NEEDED, description=description)
    return None


def _read(repo: Repository, entry: Entry) -> str:
    out = repo.blob(entry, DOC_BYTES)
    text = out.text
    return text + "\n[… cut: the file is longer than the server reads for guidance]" if out.cut else text


def found_in(repo: Repository, at: At, folder: str = "", *, everything: bool = False) -> list[tuple[Entry, str]]:
    """Convention files under a folder of a repository, with their paths from that folder; only those its include /
    exclude serves, unless `everything`."""
    files, _ = repo.files(at, folder)
    prefix = f"{folder}/" if folder else ""
    out = []
    for entry in files:
        if entry.kind != "blob" or entry.is_link or not entry.path.startswith(prefix):
            continue
        relative = entry.path[len(prefix) :]
        if is_guidance(relative) and (everything or repo.matcher.allows(entry.path)):
            out.append((entry, relative))
    return out


def from_repository(repo: Repository, folder: str = "", *, origin: str | None = None) -> list[Doc]:
    """The guidance a repository's convention files give — its own (`origin` None), or a `from` folder's."""
    at = repo.resolve(None)
    where = f"{repo.name} @ {at.label} {at.short}"
    docs = []
    for entry, relative in found_in(repo, at, folder):
        name = relative if origin is None else f"{origin}:{entry.path}"
        doc = _doc(name, where, relative, _read(repo, entry))
        if doc is not None:
            docs.append(doc)
    order = {ALWAYS: 0, SCOPED: 1, WHEN_NEEDED: 2}
    return sorted(docs, key=lambda d: (order[d.kind], ROOT_FILES.index(d.name) if d.name in ROOT_FILES else 9, d.name))


def from_files(repo: Repository, source: GuidanceSource) -> list[Doc]:
    """Files a `from` entry names by pattern — each in force for the whole repository it guides."""
    at = repo.resolve(None)
    folder = source.path.strip("/")
    wanted = Matcher(include=source.files)
    prefix = f"{folder}/" if folder else ""
    docs = []
    files, _ = repo.files(at, folder)
    for entry in sorted(files, key=lambda e: e.path):
        relative = entry.path[len(prefix) :]
        if entry.kind == "blob" and not entry.is_link and repo.matcher.allows(entry.path) and wanted.allows(relative):
            where = f"{repo.name} @ {at.label} {at.short}"
            docs.append(Doc(f"{repo.name}:{entry.path}", where, _read(repo, entry), ALWAYS))
    return docs


def gather(config: RepositoryConfig, server_docs: list[TextDoc], repositories: dict[str, Repository]) -> Guidance:
    """All the guidance for one repository, in the order an agent reads it: the server's configuration, the
    repository's entry, its `from` sources, then its own files. The same text twice is kept once."""
    docs: list[Doc] = []
    for text in [*server_docs, *config.guidance.docs]:
        docs.append(Doc(text.name, text.source, text.text, ALWAYS))
    for source in config.guidance.sources:
        repo = repositories[source.repo]
        if source.files is not None:
            docs += from_files(repo, source)
        else:
            docs += from_repository(repo, source.path.strip("/"), origin=repo.name)
    if config.guidance.own:
        docs += from_repository(repositories[config.name])
    seen: set[str] = set()
    kept = []
    for doc in docs:
        digest = hashlib.sha256(doc.text.strip().encode()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        kept.append(doc)
    return Guidance(kept)


def out_of_reach(repo: Repository) -> list[str]:
    """Convention files of a repository its include / exclude keeps from agents — for `--check` to warn about."""
    try:
        at = repo.resolve(None)
    except ReadError:
        return []
    every = {entry.path for entry, _ in found_in(repo, at, everything=True)}
    served = {entry.path for entry, _ in found_in(repo, at)}
    return sorted(every - served)


# --- delivery -----------------------------------------------------------------------------------------------------
#
# MCP keeps no session between requests (protocol revision 2026-07-28), so the server can't know what an agent has read
# in its conversation. Every answer about a repository with guidance says so in one line; an answer touching a path a
# short scoped rule covers carries that rule's text; read_guidance gives the whole of it.

OPEN = "=== {title} ==="
CLOSE = "=== End of guidance — the answer follows ===\n\n"
END = "=== End of guidance ===\n"
INLINE_SCOPED = 1500  # scoped guidance up to this long comes with the answer itself; longer, as a pointer


def _scope(doc: Doc) -> str:
    return ", ".join(p.lstrip("/") for p in doc.scope)


def _section(doc: Doc) -> str:
    where = f" — for {_scope(doc)}" if doc.kind == SCOPED else ""
    return f"--- {doc.name} ({doc.source}){where} ---\n{doc.text.strip()}\n"


def _call(repo: str, doc: Doc | None = None) -> str:
    name = f', name="{doc.name.removeprefix("skill ")}"' if doc else ""
    return f'read_guidance(repo="{repo}"{name})'


def _pointer(doc: Doc, repo: str, fits: bool = True) -> str:
    if not fits:
        return f"- `{doc.name}` — did not fit here: {_call(repo, doc)}"
    if doc.kind == SCOPED:
        return f"- `{doc.name}` — for {_scope(doc)}: comes with answers there, or {_call(repo, doc)}"
    about = f": {doc.description}" if doc.description else ""
    return f"- `{doc.name}`{about} — read it with {_call(repo, doc)} when it fits the task"


def notice(repo: str) -> str:
    """The line every answer about a repository with guidance starts with."""
    return (
        f"[`{repo}` carries guidance for agents from its owners: call {_call(repo)} once in this conversation, before "
        "you rely on this answer, and follow it.]\n\n"
    )


def render(repo: str, guidance: Guidance, budget: int) -> str:
    """All of a repository's guidance (read_guidance): what is in force everywhere and for some paths, in full while it
    fits; the rest, and the skills, named."""
    parts = [
        OPEN.format(title=f"Guidance for `{repo}`")
        + f"\nWritten for agents by the people who run this server and own `{repo}` — follow it while you work with "
        f"`{repo}`.\n"
    ]
    left = []
    for doc in guidance.of_kind(ALWAYS) + guidance.of_kind(SCOPED):
        section = _section(doc)
        if sum(map(len, parts)) + len(section) > budget - 600:
            left.append(doc)
        else:
            parts.append(section)
    pointers = [_pointer(doc, repo, fits=False) for doc in left]
    pointers += [_pointer(doc, repo) for doc in guidance.of_kind(WHEN_NEEDED)]
    if pointers:
        parts.append("More, when it applies:\n" + "\n".join(pointers) + "\n")
    return "\n".join(parts) + END


def render_scoped(repo: str, path: str, docs: list[Doc]) -> str:
    """Guidance for the path an answer is about: short rules in full, longer ones named."""
    short = [doc for doc in docs if len(doc.text) <= INLINE_SCOPED]
    if sum(len(doc.text) for doc in short) > INLINE_SCOPED:
        short = []
    body = "".join(_section(doc) for doc in short)
    pointers = "".join(_pointer(doc, repo) + "\n" for doc in docs if doc not in short)
    title = f"Guidance for `{path}` in `{repo}` — follow it while you work there"
    return OPEN.format(title=title) + "\n" + body + pointers + CLOSE


def render_one(repo: str, doc: Doc) -> str:
    kind = {
        ALWAYS: "in force for the whole repository",
        SCOPED: f"in force for {_scope(doc)}",
        WHEN_NEEDED: "to follow when it fits the task",
    }[doc.kind]
    return OPEN.format(title=f"Guidance for `{repo}`: {doc.name} — {kind}") + "\n" + _section(doc) + END


class Guide:
    """Each repository's guidance, gathered again when a repository it comes from moves."""

    def __init__(self, config: Config, repositories: dict[str, Repository]):
        self.config = config
        self.repositories = repositories
        self._gathered: dict[str, tuple[tuple[str, ...], Guidance]] = {}

    def of(self, name: str) -> Guidance:
        repo = self.repositories[name]
        key = []
        for each in [name, *(source.repo for source in repo.config.guidance.sources)]:
            try:
                key.append(self.repositories[each].resolve(None).commit)
            except ReadError:
                key.append("")
        cached = self._gathered.get(name)
        if cached is not None and cached[0] == tuple(key):
            return cached[1]
        guidance = gather(repo.config, self.config.guidance, self.repositories)
        self._gathered[name] = (tuple(key), guidance)
        return guidance

    def due(self, name: str, path: str | None) -> str:
        """What an answer about a repository (and a path in it) carries before its own text."""
        guidance = self.of(name)
        if not guidance.docs:
            return ""
        text = notice(name)
        scoped = [doc for doc in guidance.of_kind(SCOPED) if path and doc.applies_to(path)]
        if scoped:
            text += render_scoped(name, path, scoped)
        return text
