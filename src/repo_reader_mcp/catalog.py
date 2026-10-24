"""The repositories served right now (docs/remote-repositories.md, "Groups").

Those the configuration lists one by one, and the members of its groups as their hosts last listed them. A group is
listed again before every sync: a new repository joins, an archived or deleted one leaves. The set is replaced whole,
so a tool always reads one consistent set; the last listing is kept on disk, so a restart serves the members at once
(and a server whose host can't be reached keeps serving what it had).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from .config import NAME_PATTERN, Config, Group, member_config
from .hosts import HostError, list_repositories
from .mirror import Mirror, sync_all
from .repository import Repository

log = logging.getLogger("repo_reader_mcp")

PATH_PATTERN = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+$")


def plain_path(path: str) -> bool:
    """Whether a host's path for a repository (`acme/shop-api`) is plain: no part that git or an address would read
    as anything but a name (`..` would step out of the owner)."""
    return bool(PATH_PATTERN.fullmatch(path)) and not any(part in (".", "..") for part in path.split("/"))


@dataclass(frozen=True)
class Member:
    name: str
    path: str  # acme/shop-api, on its host
    description: str | None = None


@dataclass(frozen=True)
class Listing:
    """A group as its host last listed it."""

    members: tuple[Member, ...] = ()
    left_out: tuple[str, ...] = ()  # `acme/shop-old: archived`, …
    listed: str | None = None  # when the host last listed it
    failed: str | None = None  # when listing it last failed, if it did after that
    error: str | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def resolve(group: Group) -> Listing:
    """The group's members, as its host lists them now: taken by the pattern, less `skip`, archived repositories and
    names this server can't serve."""
    token = None
    if group.token_env:
        token = os.environ.get(group.token_env)
        if not token:
            raise HostError(f"the variable {group.token_env} is not set in the server's environment")
    found = list_repositories(group.host, group.owner, subgroups=group.subgroups, token=token)
    members, left_out = [], []
    for item in sorted(found, key=lambda each: each.path.lower()):
        if not group.takes(item.path):
            continue
        name = item.path.rsplit("/", 1)[-1]
        if group.skips(item.path):
            left_out.append(f"{item.path}: skipped")
        elif item.archived:
            left_out.append(f"{item.path}: archived")
        elif not plain_path(item.path) or not re.fullmatch(NAME_PATTERN, name):
            left_out.append(f"{item.path}: its name can't name a repository here")
        else:
            members.append(Member(name, item.path, item.description))
    return Listing(tuple(members), tuple(left_out), _now())


def identity(url: str) -> tuple[str, str]:
    """A repository's host and path, as hosts compare them — the same repository however its address is spelt
    (`https://Example.com/acme/shop.git`, `git@example.com:acme/shop`)."""
    if "://" in url:
        parts = urlsplit(url)
        host, path = parts.hostname or "", parts.path
    else:
        host, _, path = url.partition(":")
        host = host.rsplit("@", 1)[-1]
    return host.lower(), path.strip("/").removesuffix(".git").lower()


def listing_file(folder: str, group: Group) -> Path:
    """Where a group's last listing is kept: named by the group, and by what decides its members."""
    made_of = json.dumps([group.kind, group.host.api, group.owner, group.pattern, sorted(group.skip), group.token_env])
    slug = re.sub(r"[^A-Za-z0-9._-]+", ".", group.owner)
    return Path(folder) / f"{group.kind}-{slug}-{hashlib.sha256(made_of.encode()).hexdigest()[:12]}.members.json"


def _load(file: Path, group: Group) -> Listing:
    """A group's kept listing — each member checked again as if the host had just listed it, so a file written by
    anything else can't add a repository the group doesn't take."""
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
        members = tuple(
            Member(each["name"], each["path"], each.get("description"))
            for each in data.get("members", ())
            if plain_path(each.get("path", ""))
            and each.get("name") == each["path"].rsplit("/", 1)[-1]
            and re.fullmatch(NAME_PATTERN, each["name"])
            and group.takes(each["path"])
            and not group.skips(each["path"])
        )
        return Listing(
            members, tuple(data.get("left_out", ())), data.get("listed"), data.get("failed"), data.get("error")
        )
    except (OSError, ValueError, AttributeError, TypeError, KeyError):
        return Listing()


def _save(file: Path, listing: Listing) -> None:
    data = {
        "members": [{"name": m.name, "path": m.path, "description": m.description} for m in listing.members],
        "left_out": list(listing.left_out),
        "listed": listing.listed,
        "failed": listing.failed,
        "error": listing.error,
    }
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        temporary = file.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        temporary.write_text(json.dumps(data), encoding="utf-8")
        os.replace(temporary, file)
    except OSError as problem:
        log.warning("can't keep a group's listing in %s: %s", file, problem)


class Catalog(Mapping[str, Repository]):
    """The repositories served right now, by name: those listed one by one first, then each group's members."""

    def __init__(self, config: Config):
        self.config = config
        self._lock = threading.Lock()
        self._fixed = {repo.name: Repository(repo) for repo in config.repositories}
        self._fixed_at = {identity(repo.remote.url): repo.name for repo in config.repositories if repo.remote}
        self.listings = [_load(listing_file(config.mirrors_folder, group), group) for group in config.groups]
        self.clashes: list[str] = []
        self._pinned: ContextVar[dict[str, Repository] | None] = ContextVar(f"catalog-{id(self)}", default=None)
        self._current: dict[str, Repository] = {}
        self._current = self._build()

    @contextmanager
    def pinned(self) -> Iterator[None]:
        """The set as it is now, for everything read inside — one tool call sees one set, whatever a refresh does
        meanwhile."""
        token = self._pinned.set(self._now())
        try:
            yield
        finally:
            self._pinned.reset(token)

    def _now(self) -> dict[str, Repository]:
        pinned = self._pinned.get()
        return pinned if pinned is not None else self._current

    def __getitem__(self, name: str) -> Repository:
        return self._now()[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._now())

    def __len__(self) -> int:
        return len(self._now())

    def listed(self) -> dict[str, Repository]:
        """What agents may name."""
        return {name: repo for name, repo in self._now().items() if repo.config.listed}

    def mirrors(self) -> list[Mirror]:
        return [repo.mirror for repo in self._now().values() if repo.mirror is not None]

    def scrub(self, text: str) -> str:
        """Text with every token the configuration names taken out."""
        names = {repo.remote.token_env for repo in self.config.repositories if repo.remote}
        names |= {group.token_env for group in self.config.groups} | {self.config.http.token_env}
        for name in names - {None}:
            value = os.environ.get(name)
            if value:
                text = text.replace(value, "***")
        return text

    def _build(self) -> dict[str, Repository]:
        """The set from the listings: a member keeps its Repository while its settings stay the same. A repository
        already served — listed one by one at the same address (it would otherwise be served twice, the second time
        without that entry's include / exclude) — or a name already taken (by a repository listed one by one, or an
        earlier member) is left out and said so."""
        current = dict(self._fixed)
        clashes = []
        for group, listing in zip(self.config.groups, self.listings, strict=True):
            for member in listing.members:
                clash = self.clash(group, member, current)
                if clash:
                    clashes.append(f"{member.path} ({group.label}): {clash} — left out")
                    continue
                config = member_config(group, self.config.mirrors_folder, member.name, member.path, member.description)
                before = self._current.get(member.name)
                current[member.name] = before if before is not None and before.config == config else Repository(config)
        self.clashes = clashes
        return current

    def clash(self, group: Group, member: Member, taken: Mapping[str, Repository]) -> str | None:
        """Why a group's member can't be served beside the repositories in `taken`, if it can't."""
        served_as = self._fixed_at.get(identity(group.host.git_url(member.path)))
        if served_as is not None:
            return f"already served as `{served_as}`"
        if member.name in taken:
            return f"the name `{member.name}` is taken"
        return None

    def refresh(self) -> list[tuple[Group, str, bool]]:
        """Every group listed by its host again, and the set rebuilt: each group with what changed (or why listing it
        failed — it then keeps the members it had), and whether listing it worked."""
        results = []
        with self._lock:
            for i, group in enumerate(self.config.groups):
                before = self.listings[i]
                try:
                    listing = resolve(group)
                except HostError as error:
                    self.listings[i] = replace(before, failed=_now(), error=str(error))
                    results.append((group, str(error), False))
                else:
                    self.listings[i] = listing
                    results.append((group, _change(before, listing), True))
                _save(listing_file(self.config.mirrors_folder, group), self.listings[i])
            self._current = self._build()
        for clash in self.clashes:
            log.warning("%s", clash)
        return results


def _change(before: Listing, after: Listing) -> str:
    names = [member.name for member in after.members]
    joined = sorted(set(names) - {member.name for member in before.members})
    left = sorted({member.name for member in before.members} - set(names))
    line = f"{len(names)} repositor{'y' if len(names) == 1 else 'ies'}"
    if before.listed is not None and joined:
        line += f"; joined: {', '.join(joined)}"
    if before.listed is not None and left:
        line += f"; left: {', '.join(left)}"
    if after.left_out:
        line += f"; left out: {len(after.left_out)}"
    return line


def sync_round(catalog: Catalog) -> bool:
    """One round: the groups listed, then every mirror synced — logged to stderr; whether everything worked."""
    worked_all = True
    for group, outcome, worked in catalog.refresh():
        if worked:
            log.info("%s: %s", group.label, outcome)
        else:
            log.warning("%s: listing it failed: %s", group.label, outcome)
        worked_all = worked_all and worked
    for mirror, outcome, worked in sync_all(catalog.mirrors()):
        if worked:
            log.info("%s: %s", mirror.name, outcome)
        else:
            log.warning("%s: the sync failed: %s", mirror.name, outcome)
        worked_all = worked_all and worked
    return worked_all


def keep_fresh(catalog: Catalog, every_minutes: int) -> threading.Thread:
    """A round now, then every `every_minutes` (only now, when 0) — in the background."""

    def loop() -> None:
        while True:
            try:
                sync_round(catalog)
            except Exception as error:  # a round that fails never ends the loop: the next one tries again
                log.error("a sync round failed: %s", catalog.scrub(f"{type(error).__name__}: {error}"))
            if not every_minutes:
                return
            time.sleep(every_minutes * 60)

    thread = threading.Thread(target=loop, name="repo-reader-sync", daemon=True)
    thread.start()
    return thread
