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
from typing import Any
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .git import GitError, find_git_dir
from .paths import Matcher, PathError, clean_path, compile_pattern

NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$"
VARIABLE_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,99}$"

# Keys of the design that later versions read (dev/PLAN.md, milestone 2): named, so the message says "not yet".
NOT_YET = {
    "github": "groups of repositories (`github:`) are not supported yet — list each repository with its `url`",
    "gitlab": "groups of repositories (`gitlab:`) are not supported yet — list each repository with its `url`",
    "skip": "`skip` comes with groups of repositories, which are not supported yet",
}

# The protocols a mirror is fetched by. Remote helpers (`ext::`, which runs a command, and the like) are not among them.
PROTOCOLS = ("https", "http", "ssh", "git", "file")
SCP_LIKE = re.compile(r"^(?:[A-Za-z0-9._~-]+@)?[A-Za-z0-9][A-Za-z0-9.-]*:(?!//)\S+$")  # git@example.com:acme/shop.git
DEFAULT_MIRRORS = "~/.cache/repo-reader-mcp"


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


def name_from_url(url: str) -> str | None:
    """`shop-backend` from `https://example.com/acme/shop-backend.git` — or None when it makes no valid name."""
    path = urlsplit(url).path if "://" in url else url.partition(":")[2]
    last = path.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    return last if re.fullmatch(NAME_PATTERN, last) else None


class RepositorySettings(_Strict):
    name: str | None = Field(default=None, pattern=NAME_PATTERN)
    path: str | None = Field(default=None, min_length=1)
    url: str | None = Field(default=None, min_length=1)
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


class Settings(_Strict):
    repositories: list[RepositorySettings] = Field(min_length=1)
    mirrors: MirrorSettings = Field(default_factory=MirrorSettings)
    limits: Limits = Field(default_factory=Limits)
    guidance: ServerGuidanceSettings = Field(default_factory=ServerGuidanceSettings)


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


@dataclass(frozen=True)
class Config:
    repositories: list[RepositoryConfig] = field(default_factory=list)
    limits: Limits = field(default_factory=Limits)
    guidance: list[TextDoc] = field(default_factory=list)  # for every repository
    mirrors: MirrorSettings = field(default_factory=MirrorSettings)
    mirrors_folder: str = ""  # where remote repositories are mirrored, resolved


def mirrors_folder(settings: MirrorSettings, base: Path) -> Path:
    if settings.folder == DEFAULT_MIRRORS and os.environ.get("XDG_CACHE_HOME"):
        return Path(os.environ["XDG_CACHE_HOME"]) / "repo-reader-mcp"
    folder = Path(os.path.expanduser(settings.folder))
    return folder if folder.is_absolute() else base / folder


LOOPBACK = ("localhost", "127.0.0.1", "::1")


def mirror_dir(folder: Path, name: str, settings: RepositorySettings) -> Path:
    """A mirror's folder: its name, and a digest of what it is made from — its URL, `refs`, `include` and `exclude`.
    A mirror holds exactly what one configuration takes: another configuration sharing the folder (another server on
    the machine), or this one changed, gets a mirror of its own — never branches or contents another one fetched."""
    made_of = json.dumps([settings.url, settings.refs, settings.include, settings.exclude])
    return folder / f"{name}-{hashlib.sha256(made_of.encode()).hexdigest()[:12]}.git"


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
    names = {repo.name or name_from_url(repo.url or "") for repo in settings.repositories}
    server_guidance = _text_docs(settings.guidance, base, "guidance", problems)
    folder = mirrors_folder(settings.mirrors, base)
    for i, repo in enumerate(settings.repositories):
        name = repo.name or (name_from_url(repo.url) if repo.url else None)
        where = f"repositories[{i}]" + (f" ({name})" if name else "")
        if name is None:
            missing = "a name: none can be taken from its url" if repo.url else "a name"
            problems.append(f"{where} → name: give it {missing}")
            continue
        if name in seen:
            problems.append(f"{where} → name: `{name}` is used by an earlier repository")
        seen.add(name)
        remote = None
        if (repo.path is None) == (repo.url is None):
            problems.append(
                f"{where}: give either `path` (a repository on this server's disk) or `url` (a remote one to mirror)"
                + (", not both" if repo.path else "")
            )
            continue
        if repo.url is not None:
            protocol = url_protocol(repo.url)
            if repo.token_env and protocol not in ("http", "https"):
                problems.append(
                    f"{where} → token_env: a token goes with an https url; "
                    f"{protocol} uses what the server's own account has (its ssh keys)"
                )
                continue
            if repo.token_env and protocol == "http" and urlsplit(repo.url).hostname not in LOOPBACK:
                problems.append(f"{where} → token_env: a token is sent over https only — http would show it on the way")
                continue
            if repo.token_env and not os.environ.get(repo.token_env):
                problems.append(
                    f"{where} → token_env: the variable {repo.token_env} is not set in the server's environment"
                )
                continue
            if repo.token_user and not repo.token_env:
                problems.append(f"{where} → token_user: it goes with `token_env`")
                continue
            remote = Remote(
                repo.url,
                protocol,
                repo.token_env,
                repo.token_user or "x-access-token",
                tuple(repo.refs) if repo.refs else None,
            )
            path = mirror_dir(folder, name, repo)
            git_dir = str(path)
        else:
            stray = [key for key in ("token_env", "token_user", "refs") if getattr(repo, key) is not None]
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
        matcher = Matcher(repo.include, repo.exclude)
        repositories.append(
            RepositoryConfig(name, str(path), git_dir, repo.description, matcher, repo.listed, guidance, remote)
        )
    if problems:
        raise ConfigError(source, problems)
    return Config(repositories, settings.limits, server_guidance, settings.mirrors, str(folder))


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
