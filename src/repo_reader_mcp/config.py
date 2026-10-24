"""The configuration file: which repositories are served and how answers are sized (docs/reference/configuration.md).

A wrong entry stops the server before it starts, and every problem is named at once — the entry and the key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .git import GitError, find_git_dir
from .paths import Matcher, compile_pattern

NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$"

# Keys of the design that later versions read (dev/PLAN.md, milestone 2): named, so the message says "not yet".
NOT_YET = {
    "url": "remote repositories (`url`) are not supported yet — give `path` to a local repository",
    "token_env": "tokens (`token_env`) come with remote repositories, which are not supported yet",
    "refs": "`refs` comes with remote repositories, which are not supported yet — a local repository serves all",
    "sync": "`sync` comes with remote repositories, which are not supported yet",
}


class ConfigError(Exception):
    """The configuration can't be used; `problems` names each thing wrong."""

    def __init__(self, source: str, problems: list[str]):
        self.source = source
        self.problems = problems
        count = f"{len(problems)} problem" + ("s" if len(problems) != 1 else "")
        super().__init__(f"the configuration {source} has {count}:\n" + "\n".join(f"  - {p}" for p in problems))


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RepositorySettings(_Strict):
    name: str = Field(pattern=NAME_PATTERN)
    path: str = Field(min_length=1)
    description: str | None = None
    include: list[str] | None = Field(default=None, min_length=1)
    exclude: list[str] = Field(default_factory=list)

    @field_validator("include", "exclude")
    @classmethod
    def _patterns(cls, patterns: list[str] | None) -> list[str] | None:
        for pattern in patterns or ():
            compile_pattern(pattern)  # a ValueError names what is wrong with it
        return patterns


class Limits(_Strict):
    answer_characters: int = Field(default=40_000, ge=2_000, le=1_000_000)


class Settings(_Strict):
    repositories: list[RepositorySettings] = Field(min_length=1)
    limits: Limits = Field(default_factory=Limits)


@dataclass(frozen=True)
class RepositoryConfig:
    name: str
    path: str
    git_dir: str
    description: str | None = None
    matcher: Matcher = field(default_factory=Matcher)


@dataclass(frozen=True)
class Config:
    repositories: list[RepositoryConfig] = field(default_factory=list)
    limits: Limits = field(default_factory=Limits)


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

    problems = []
    seen: set[str] = set()
    repositories = []
    for i, repo in enumerate(settings.repositories):
        where = f"repositories[{i}] ({repo.name})"
        if repo.name in seen:
            problems.append(f"{where} → name: `{repo.name}` is used by an earlier repository")
        seen.add(repo.name)
        path = Path(os.path.expanduser(repo.path))
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
        matcher = Matcher(repo.include, repo.exclude)
        repositories.append(RepositoryConfig(repo.name, str(path), git_dir, repo.description, matcher))
    if problems:
        raise ConfigError(source, problems)
    return Config(repositories, settings.limits)


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
