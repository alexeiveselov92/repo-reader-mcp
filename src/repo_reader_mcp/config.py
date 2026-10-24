"""The configuration file: which repositories are served and how answers are sized (docs/reference/configuration.md).

A wrong entry stops the server before it starts, and every problem is named at once — the entry and the key.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .git import GitError, find_git_dir
from .hosts import GITHUB, GITLAB, TOKEN_USER, Host, host_of
from .links import Links, links_for
from .paths import Matcher, PathError, clean_path, compile_pattern

NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$"
VARIABLE_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,99}$"

# Keys of the design that later versions read (dev/PLAN.md): named here, the message says "not yet", not "unknown".
NOT_YET: dict[str, str] = {}

# The protocols a mirror is fetched by. Remote helpers (`ext::`, which runs a command, and the like) are not among them.
PROTOCOLS = ("https", "http", "ssh", "git", "file")
SCP_LIKE = re.compile(r"^(?:[A-Za-z0-9._~-]+@)?[A-Za-z0-9][A-Za-z0-9.-]*:(?!//)\S+$")  # git@example.com:acme/shop.git
DEFAULT_MIRRORS = "~/.cache/repo-reader-mcp"
HOST_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*(?::[0-9]{1,5})?$")


class ConfigError(Exception):
    """The configuration can't be used; `problems` names each thing wrong."""

    def __init__(self, source: str, problems: list[str]):
        self.source = source
        self.problems = problems
        count = f"{len(problems)} problem" + ("s" if len(problems) != 1 else "")
        super().__init__(f"the configuration {source} has {count}:\n" + "\n".join(f"  - {p}" for p in problems))


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_patterns(patterns: list[str] | None) -> list[str] | None:
    for pattern in patterns or ():
        compile_pattern(pattern)  # a ValueError names what is wrong with it
    return patterns


class GuidanceSource(_Strict):
    """A folder of another configured repository whose guidance applies to this one."""

    repo: str
    path: str = ""
    files: list[str] | None = Field(default=None, min_length=1)  # given: exactly these files, in force everywhere

    @field_validator("path")
    @classmethod
    def _plain(cls, path: str) -> str:
        try:
            return clean_path(path, allow_root=True)
        except PathError as error:
            raise ValueError(str(error)) from None

    _files = field_validator("files")(_check_patterns)


class ServerGuidanceSettings(_Strict):
    text: str | None = None
    files: list[str] = Field(default_factory=list)


class GuidanceSettings(ServerGuidanceSettings):
    sources: list[GuidanceSource] = Field(default_factory=list, alias="from")
    own: bool = True


def url_protocol(url: str) -> str:
    """The protocol a remote repository's URL is fetched by — or a ValueError saying why it can't be served."""
    if any(ord(ch) <= 32 or ord(ch) == 127 for ch in url):
        raise ValueError("a url can't contain spaces or control characters")
    if "://" in url:
        protocol = url.split("://", 1)[0].lower()
        if protocol not in PROTOCOLS:
            raise ValueError(
                f"`{protocol}://` is not a protocol this server fetches by — https, http, ssh, git or file"
            )
        parts = urlsplit(url)
        if parts.password is not None or (protocol in ("http", "https") and parts.username is not None):
            raise ValueError("a url can't carry credentials — name the variable that holds a token in `token_env`")
        if parts.query or parts.fragment or url.endswith(("?", "#")):
            raise ValueError("a url can't carry a query or a fragment (`?…`, `#…`) — agents are shown the url")
        if protocol != "file" and not parts.hostname:
            raise ValueError(f"`{url}` names no host")
        return protocol
    if "::" in url:
        raise ValueError("remote helpers (`<name>::…`) are not a protocol this server fetches by")
    if SCP_LIKE.fullmatch(url):
        return "ssh"
    raise ValueError(
        "`url` is a remote repository's address (https://…, ssh://…, git@host:path, file://…); "
        "a repository on this server's disk is given by `path`"
    )


def split_group(kind: str, spec: str) -> tuple[str, str]:
    """`acme` and `shop-*` from `acme/shop-*`: the owner — written whole; for GitLab, a group's full path — and the
    pattern its repositories' names are taken by (GitLab's `**/` reaches into subgroups)."""
    parts = spec.strip("/").split("/")
    if any(ord(ch) <= 32 or ord(ch) == 127 for ch in spec) or any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"`{spec}` is not an owner and a pattern, like acme/shop-*")
    if kind == GITHUB and len(parts) != 2:
        raise ValueError(f"`{spec}` is not an owner and a pattern of names, like acme/shop-*")
    cut = parts.index("**") if "**" in parts else len(parts) - 1
    owner, pattern = parts[:cut], parts[cut:]
    if not owner or any(ch in part for part in owner for ch in "*?"):
        raise ValueError(f"`{spec}` names no owner: it is written whole before the pattern, like acme/shop-*")
    compile_pattern("/" + "/".join(pattern))
    return "/".join(owner), "/".join(pattern)


def host_address(host: str) -> str:
    """A code host's address as written in `host` — or a ValueError saying why it can't be one."""
    if "://" not in host:
        if not HOST_NAME.fullmatch(host.strip("/")):
            raise ValueError(f"`{host}` is not a host's name (git.example.com) nor its address (https://…)")
        return host
    parts = urlsplit(host)
    if parts.scheme.lower() not in ("https", "http"):
        raise ValueError("a host's address is https:// (or http://)")
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise ValueError("a host's address can't carry credentials, a query or a fragment")
    if not parts.hostname:
        raise ValueError(f"`{host}` names no host")
    try:
        _ = parts.port  # reading it checks it
    except ValueError:
        raise ValueError(f"`{host}` has a port that is not a number from 1 to 65535") from None
    return host


def name_from_url(url: str) -> str | None:
    """`shop-backend` from `https://example.com/acme/shop-backend.git` — or None when it makes no valid name."""
    path = urlsplit(url).path if "://" in url else url.partition(":")[2]
    last = path.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    return last if re.fullmatch(NAME_PATTERN, last) else None


class RepositorySettings(_Strict):
    name: str | None = Field(default=None, pattern=NAME_PATTERN)
    path: str | None = Field(default=None, min_length=1)
    url: str | None = Field(default=None, min_length=1)
    github: str | None = Field(default=None, min_length=1)
    gitlab: str | None = Field(default=None, min_length=1)
    host: str | None = Field(default=None, min_length=1)
    skip: list[str] | None = Field(default=None, min_length=1)
    links: Literal["github", "gitlab", "bitbucket", "none"] | None = None
    forks: bool | None = None
    serve_credential_files: bool = False
    token_env: str | None = Field(default=None, pattern=VARIABLE_PATTERN)
    token_user: str | None = Field(default=None, min_length=1, pattern=r"^[^:\s]+$")
    refs: list[str] | None = Field(default=None, min_length=1)
    description: str | None = None
    listed: bool = True
    include: list[str] | None = Field(default=None, min_length=1)
    exclude: list[str] = Field(default_factory=list)
    guidance: GuidanceSettings = Field(default_factory=GuidanceSettings)

    _patterns = field_validator("include", "exclude")(_check_patterns)

    @field_validator("url")
    @classmethod
    def _url(cls, url: str | None) -> str | None:
        if url is not None:
            url_protocol(url)
        return url

    @field_validator("host")
    @classmethod
    def _host(cls, host: str | None) -> str | None:
        return host_address(host) if host is not None else None

    @field_validator("skip")
    @classmethod
    def _skip(cls, skip: list[str] | None) -> list[str] | None:
        for item in skip or ():
            compile_pattern("/" + item.strip("/"))
        return skip

    @field_validator("refs")
    @classmethod
    def _refs(cls, refs: list[str] | None) -> list[str] | None:
        for ref in refs or ():
            if not ref or any(ord(ch) <= 32 or ord(ch) == 127 for ch in ref):
                raise ValueError(f"`{ref}` is not a branch or tag name, nor a pattern of them")
        return refs


class MirrorSettings(_Strict):
    folder: str = DEFAULT_MIRRORS
    every_minutes: int = Field(default=10, ge=0, le=1440)


class Limits(_Strict):
    answer_characters: int = Field(default=40_000, ge=2_000, le=1_000_000)


class HttpSettings(_Strict):
    """Serving over Streamable HTTP (`--http`): who may call."""

    token_env: str | None = Field(default=None, pattern=VARIABLE_PATTERN)  # the variable holding the bearer token
    behind_gateway: bool = False  # no token here: a gateway in front checks who calls


class Settings(_Strict):
    repositories: list[RepositorySettings] = Field(min_length=1)
    mirrors: MirrorSettings = Field(default_factory=MirrorSettings)
    limits: Limits = Field(default_factory=Limits)
    guidance: ServerGuidanceSettings = Field(default_factory=ServerGuidanceSettings)
    http: HttpSettings = Field(default_factory=HttpSettings)


@dataclass(frozen=True)
class TextDoc:
    """Guidance written in the configuration, or in a file on the server's disk it names — read at start."""

    name: str
    source: str
    text: str


@dataclass(frozen=True)
class RepositoryGuidance:
    docs: list[TextDoc] = field(default_factory=list)
    sources: list[GuidanceSource] = field(default_factory=list)
    own: bool = True


@dataclass(frozen=True)
class Remote:
    """Where a mirrored repository comes from, and what of it the mirror keeps."""

    url: str
    protocol: str
    token_env: str | None = None  # the variable holding a token — its name, never its value
    token_user: str = "x-access-token"
    refs: tuple[str, ...] | None = None  # branch and tag names or patterns; None keeps them all


@dataclass(frozen=True)
class RepositoryConfig:
    name: str
    path: str  # the repository's folder on disk — for a remote one, its mirror
    git_dir: str
    description: str | None = None
    matcher: Matcher = field(default_factory=Matcher)
    listed: bool = True
    guidance: RepositoryGuidance = field(default_factory=RepositoryGuidance)
    remote: Remote | None = None
    group: str | None = None  # the group it belongs to (`github: acme/shop-*`), when it is a member of one
    links: Links | None = None  # the host's pages for what answers show


@dataclass(frozen=True)
class Group:
    """An entry naming repositories by a pattern (`github: acme/shop-*`): the host lists them on every sync, and each
    member is served with the entry's settings, named by its own repository's name."""

    kind: str  # github | gitlab
    spec: str  # acme/shop-*, as written
    owner: str  # acme — for GitLab, a group's full path
    pattern: str  # shop-*
    host: Host
    skip: tuple[str, ...] = ()
    token_env: str | None = None
    token_user: str = "x-access-token"
    refs: tuple[str, ...] | None = None
    include: tuple[str, ...] | None = None
    exclude: tuple[str, ...] = ()
    description: str | None = None
    listed: bool = True
    guidance: RepositoryGuidance = field(default_factory=RepositoryGuidance)
    matcher: Matcher = field(default_factory=Matcher)  # one for every member
    links: str | None = None  # the kind of the host's pages: the group's own unless `links` says otherwise
    forks: bool = False  # whether forks are taken
    credential_files: bool = False  # whether files named for credentials are served

    @property
    def label(self) -> str:
        public = self.host.web == f"https://{'github.com' if self.kind == GITHUB else 'gitlab.com'}"
        return f"{self.kind}: {self.spec}" + ("" if public else f" on {self.host.name}")

    @property
    def subgroups(self) -> bool:
        """Whether the pattern reaches into GitLab's subgroups: `**` (all of them) or a `/` in it."""
        return "/" in self.pattern or self.pattern == "**"

    def takes(self, path: str) -> bool:
        """Whether the pattern takes a repository at this path (`acme/shop-api`) — letters' case aside, as hosts do."""
        prefix = self.owner.lower() + "/"
        if not path.lower().startswith(prefix):
            return False
        return bool(compile_pattern("/" + self.pattern.lower()).fullmatch(path.lower()[len(prefix) :]))

    def name_of(self, path: str, *, whole: bool = False) -> str:
        """A member's name: its repository's own (`api`) — or, `whole`, its path below the owner (`legacy.api`), for
        two in a group that share a name (GitLab's subgroups)."""
        return path[len(self.owner) + 1 :].replace("/", ".") if whole else path.rsplit("/", 1)[-1]

    def skips(self, path: str) -> bool:
        """Whether `skip` leaves it out: an item with a `/` is matched against the full path, one without against the
        repository's name."""
        name = path.rsplit("/", 1)[-1].lower()
        for item in self.skip:
            item = item.strip("/").lower()
            if compile_pattern("/" + item).fullmatch(path.lower() if "/" in item else name):
                return True
        return False


@dataclass(frozen=True)
class Config:
    repositories: list[RepositoryConfig] = field(default_factory=list)
    limits: Limits = field(default_factory=Limits)
    guidance: list[TextDoc] = field(default_factory=list)  # for every repository
    mirrors: MirrorSettings = field(default_factory=MirrorSettings)
    mirrors_folder: str = ""  # where remote repositories are mirrored, resolved
    groups: list[Group] = field(default_factory=list)
    http: HttpSettings = field(default_factory=HttpSettings)


def mirrors_folder(settings: MirrorSettings, base: Path) -> Path:
    if settings.folder == DEFAULT_MIRRORS and os.environ.get("XDG_CACHE_HOME"):
        return Path(os.environ["XDG_CACHE_HOME"]) / "repo-reader-mcp"
    folder = Path(os.path.expanduser(settings.folder))
    return folder if folder.is_absolute() else base / folder


LOOPBACK = ("localhost", "127.0.0.1", "::1")


def mirror_dir(
    folder: Path,
    name: str,
    url: str,
    refs: Any = None,
    include: Any = None,
    exclude: Any = (),
    token_env: str | None = None,
    credential_files: bool = False,
) -> Path:
    """A mirror's folder: its name, and a digest of what it is made from — its URL, `refs`, `include`, `exclude` and
    the name of the variable its token is in. A mirror holds exactly what one configuration takes: another configuration
    sharing the folder (another server on the machine), or this one changed, gets a mirror of its own — never branches
    or contents another one fetched, nor what was fetched with a token by one that names none."""
    made_of = [url, list(refs) if refs else None, list(include) if include else None, list(exclude), token_env]
    made_of += ["credential files"] if credential_files else []  # it holds them: never one for a server that doesn't
    return folder / f"{name}-{hashlib.sha256(json.dumps(made_of).encode()).hexdigest()[:12]}.git"


def member_config(group: Group, folder: str, name: str, path: str, description: str | None) -> RepositoryConfig:
    """A group's member as a repository: mirrored from the address built from the host and its path, with the
    entry's settings; described by the entry and by the host."""
    url = group.host.git_url(path)
    about = " — ".join(text for text in (group.description, description) if text) or None
    remote = Remote(url, url_protocol(url), group.token_env, group.token_user, group.refs)
    git_dir = str(
        mirror_dir(
            Path(folder), name, url, group.refs, group.include, group.exclude, group.token_env, group.credential_files
        )
    )
    links = links_for(url, group.links or group.kind)
    return RepositoryConfig(
        name, git_dir, git_dir, about, group.matcher, group.listed, group.guidance, remote, group.label, links
    )


def _text_docs(settings: ServerGuidanceSettings, base: Path, where: str, problems: list[str]) -> list[TextDoc]:
    """The configuration's own guidance: its text, and the files it names, read now."""
    docs = []
    if settings.text and settings.text.strip():
        docs.append(TextDoc("configuration", "the server's configuration", settings.text.strip()))
    for i, name in enumerate(settings.files):
        file = Path(os.path.expanduser(name))
        file = file if file.is_absolute() else base / file
        try:
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            problems.append(f"{where} → files[{i}]: can't read {file}: {getattr(error, 'strerror', None) or error}")
            continue
        docs.append(TextDoc(f"configuration:{file.name}", f"the server's file {file}", text.strip()))
    return docs


def _where(loc: tuple[Any, ...], data: Any) -> str:
    """`repositories[1] (shop-frontend) → path` from pydantic's location of an error."""
    out = []
    node = data
    for part in loc:
        if isinstance(part, int):
            out[-1] += f"[{part}]"
            node = node[part] if isinstance(node, list) and part < len(node) else None
            if isinstance(node, dict) and isinstance(node.get("name"), str):
                out[-1] += f" ({node['name']})"
            elif isinstance(node, dict) and any(isinstance(node.get(kind), str) for kind in (GITHUB, GITLAB)):
                kind = GITHUB if isinstance(node.get(GITHUB), str) else GITLAB
                out[-1] += f" ({kind}: {node[kind]})"
            elif isinstance(node, dict) and isinstance(node.get("url"), str) and name_from_url(node["url"]):
                out[-1] += f" ({name_from_url(node['url'])})"
        else:
            out.append(str(part))
            node = node.get(part) if isinstance(node, dict) else None
    return " → ".join(out) or "the file"


def _schema_problems(error: ValidationError, data: Any) -> list[str]:
    problems = []
    for item in error.errors():
        where = _where(item["loc"], data)
        key = str(item["loc"][-1]) if item["loc"] else ""
        if item["type"] == "extra_forbidden":
            message = NOT_YET.get(key, "an unknown key")
        elif item["type"] == "string_pattern_mismatch" and key == "name":
            message = "a name is up to 100 letters, digits, `.`, `_` or `-`, starting with a letter or digit"
        elif item["type"] == "string_pattern_mismatch" and key == "token_env":
            message = "the name of an environment variable (like GITHUB_TOKEN) — never the token itself"
        elif item["type"] == "value_error":
            message = str(item["ctx"]["error"])
        else:
            message = item["msg"][0].lower() + item["msg"][1:]
        problems.append(f"{where}: {message}")
    return problems


def _token_problem(repo: RepositorySettings, protocol: str, hostname: str | None) -> str | None:
    """What is wrong with an entry's token settings, if anything — for a URL's or a host's protocol."""
    if repo.token_env and protocol not in ("http", "https"):
        return (
            f"token_env: a token goes with an https url; {protocol} uses what the server's own account has "
            "(its ssh keys)"
        )
    if repo.token_env and protocol == "http" and hostname not in LOOPBACK:
        return "token_env: a token is sent over https only — http would show it on the way"
    if repo.token_env and not os.environ.get(repo.token_env):
        return f"token_env: the variable {repo.token_env} is not set in the server's environment"
    if repo.token_user and not repo.token_env:
        return "token_user: it goes with `token_env`"
    return None


def _group(repo: RepositorySettings, where: str, base: Path, problems: list[str]) -> Group | None:
    """A group's entry, checked — or None, with what is wrong in `problems`."""
    kind = GITHUB if repo.github is not None else GITLAB
    spec = (repo.github or repo.gitlab or "").strip("/")
    if repo.name is not None:
        problems.append(f"{where} → name: each repository of a group is named by its own name — a group takes none")
        return None
    if not repo.listed:
        problems.append(
            f"{where} → listed: a group's repositories can't be guidance sources, so `listed: false` would serve "
            "nothing"
        )
        return None
    try:
        owner, pattern = split_group(kind, spec)
    except ValueError as error:
        problems.append(f"{where} → {kind}: {error}")
        return None
    host = host_of(kind, repo.host)
    problem = _token_problem(repo, urlsplit(host.web).scheme, urlsplit(host.web).hostname)
    if problem:
        problems.append(f"{where} → {problem}")
        return None
    for j, item in enumerate(repo.skip or ()):
        if "/" in item.strip("/") and not item.strip("/").lower().startswith(owner.lower() + "/"):
            problems.append(f"{where} → skip[{j}]: `{item}` is not a repository of `{owner}`")
    guidance = RepositoryGuidance(
        _text_docs(repo.guidance, base, f"{where} → guidance", problems), repo.guidance.sources, repo.guidance.own
    )
    return Group(
        kind,
        spec,
        owner,
        pattern,
        host,
        tuple(repo.skip or ()),
        repo.token_env,
        repo.token_user or TOKEN_USER[kind],
        tuple(repo.refs) if repo.refs else None,
        tuple(repo.include) if repo.include else None,
        tuple(repo.exclude),
        repo.description,
        repo.listed,
        guidance,
        Matcher(repo.include, repo.exclude, credentials=not repo.serve_credential_files),
        repo.links,
        bool(repo.forks),
        repo.serve_credential_files,
    )


def parse_config(data: Any, base: Path, source: str = "") -> Config:
    """The configuration from already-loaded YAML; relative paths are taken from `base`."""
    if not isinstance(data, dict):
        raise ConfigError(source, ["the file must be a mapping with `repositories:` in it"])
    try:
        settings = Settings.model_validate(data)
    except ValidationError as error:
        raise ConfigError(source, _schema_problems(error, data)) from None

    problems: list[str] = []
    seen: set[str] = set()
    repositories = []
    groups = []
    # The repositories `from` can name: those listed one by one (a group's members are known only once listed).
    names = {
        repo.name or name_from_url(repo.url or "")
        for repo in settings.repositories
        if repo.github is None and repo.gitlab is None
    }
    server_guidance = _text_docs(settings.guidance, base, "guidance", problems)
    folder = mirrors_folder(settings.mirrors, base)
    for i, repo in enumerate(settings.repositories):
        given = [key for key in ("path", "url", GITHUB, GITLAB) if getattr(repo, key) is not None]
        if len(given) > 1:
            label = f" ({repo.name or getattr(repo, given[0])})" if given[0] != "path" or repo.name else ""
            problems.append(
                f"repositories[{i}]{label}: give one of `path`, `url`, `github`, `gitlab` — not "
                + " and ".join(f"`{key}`" for key in given)
            )
            continue
        if given and given[0] in (GITHUB, GITLAB):
            where = f"repositories[{i}] ({given[0]}: {getattr(repo, given[0])})"
            for j, origin in enumerate(repo.guidance.sources):
                if origin.repo not in names:
                    problems.append(
                        f"{where} → guidance → from[{j}] → repo: names `{origin.repo}`, which is not configured "
                        "one by one (a group's repository can't be a source)"
                    )
            group = _group(repo, where, base, problems)
            if group is not None:
                groups.append(group)
            continue
        name = repo.name or (name_from_url(repo.url) if repo.url else None)
        where = f"repositories[{i}]" + (f" ({name})" if name else "")
        stray = [key for key in ("skip", "host", "forks") if getattr(repo, key) is not None]
        if stray:
            problems.append(f"{where} → {stray[0]}: it goes with a group of repositories (`github:` or `gitlab:`)")
            continue
        if name is None:
            missing = "a name: none can be taken from its url" if repo.url else "a name"
            problems.append(f"{where} → name: give it {missing}")
            continue
        if name in seen:
            problems.append(f"{where} → name: `{name}` is used by an earlier repository")
        seen.add(name)
        remote = None
        if not given:
            problems.append(
                f"{where}: give `path` (a repository on this server's disk), `url` (a remote one to mirror), or "
                "`github:` / `gitlab:` (a group of them)"
            )
            continue
        if repo.url is not None:
            protocol = url_protocol(repo.url)
            problem = _token_problem(repo, protocol, urlsplit(repo.url).hostname if "://" in repo.url else None)
            if problem:
                problems.append(f"{where} → {problem}")
                continue
            remote = Remote(
                repo.url,
                protocol,
                repo.token_env,
                repo.token_user or "x-access-token",
                tuple(repo.refs) if repo.refs else None,
            )
            path = mirror_dir(
                folder,
                name,
                repo.url,
                repo.refs,
                repo.include,
                repo.exclude,
                repo.token_env,
                repo.serve_credential_files,
            )
            git_dir = str(path)
        else:
            stray = [key for key in ("token_env", "token_user", "refs", "links") if getattr(repo, key) is not None]
            if stray:
                problems.append(
                    f"{where} → {stray[0]}: it is for a remote repository (`url`) — "
                    "a repository on this server's disk serves every branch and tag as it is"
                )
                continue
            path = Path(os.path.expanduser(repo.path or ""))
            if not path.is_absolute():
                path = base / path
            if not path.is_dir():
                problems.append(f"{where} → path: {path} is not a folder")
                continue
            try:
                git_dir = find_git_dir(str(path))
            except GitError as error:
                problems.append(f"{where} → path: {path} is not a git repository's top: {error}")
                continue
        for j, origin in enumerate(repo.guidance.sources):
            if origin.repo not in names or origin.repo == name:
                other = "itself" if origin.repo == name else f"`{origin.repo}`, which is not configured"
                problems.append(f"{where} → guidance → from[{j}] → repo: names {other}")
        guidance = RepositoryGuidance(
            _text_docs(repo.guidance, base, f"{where} → guidance", problems), repo.guidance.sources, repo.guidance.own
        )
        matcher = Matcher(repo.include, repo.exclude, credentials=not repo.serve_credential_files)
        links = links_for(repo.url, repo.links) if repo.url else None
        repositories.append(
            RepositoryConfig(
                name, str(path), git_dir, repo.description, matcher, repo.listed, guidance, remote, None, links
            )
        )
    if settings.http.token_env and settings.http.behind_gateway:
        problems.append("http: give `token_env` or `behind_gateway: true`, not both")
    elif settings.http.token_env and not os.environ.get(settings.http.token_env):
        variable = settings.http.token_env
        problems.append(f"http → token_env: the variable {variable} is not set in the server's environment")
    if problems:
        raise ConfigError(source, problems)
    return Config(repositories, settings.limits, server_guidance, settings.mirrors, str(folder), groups, settings.http)


def load_config(file: str | os.PathLike[str]) -> Config:
    """Read and check a configuration file; a ConfigError names everything wrong with it."""
    path = Path(file)
    source = str(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigError(source, [f"can't read it: {error.strerror or error}"]) from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        line = f" at line {mark.line + 1}" if mark is not None else ""
        raise ConfigError(source, [f"it is not valid YAML{line}: {getattr(error, 'problem', error)}"]) from None
    return parse_config(data, path.resolve().parent, source)
