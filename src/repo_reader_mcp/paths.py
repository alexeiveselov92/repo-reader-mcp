"""Paths inside a repository and the `include` / `exclude` patterns that decide which of them are served.

A path is always written from the repository's root (`src/app/main.py`). Patterns follow `.gitignore`'s habits, so a
pattern written to keep something out keeps it out wherever it is:

- `*` matches within one folder name, `?` one character, `**` any number of folders;
- a pattern with no `/` matches a name at any depth (`*.pem`, `secrets`);
- a pattern matches a path or any folder the path is in (`secrets` keeps out everything under every `secrets/`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable


class PathError(ValueError):
    """A path an agent gave that cannot name anything inside a repository."""


def clean_path(path: str, *, allow_root: bool = False) -> str:
    """The path from the repository's root, or a PathError saying why it can't be one."""
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in path):
        raise PathError("a path can't contain control characters")
    inner = path.strip("/")
    if not inner:
        if allow_root:
            return ""
        raise PathError("name a file, from the repository's root (like `src/app.py`)")
    parts = inner.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise PathError(f"`{path}` is not a plain path: write it from the repository's root, like `src/app.py`")
    return "/".join(parts)


def _segment(segment: str) -> str:
    out = []
    for ch in segment:
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
    return "".join(out)


def compile_pattern(pattern: str) -> re.Pattern[str]:
    """One pattern as a regular expression over a full path."""
    anchored = pattern.startswith("/")
    body = pattern.strip("/")
    if not body:
        raise ValueError("an empty pattern")
    segments = body.split("/")
    if any(part in ("", ".", "..") for part in segments):
        raise ValueError(f"`{pattern}` has an empty, `.` or `..` part")
    if len(segments) == 1 and not anchored:
        segments = ["**", *segments]
    parts = []
    for i, segment in enumerate(segments):
        last = i == len(segments) - 1
        if segment == "**":
            parts.append(".*" if last else "(?:[^/]+/)*")
        else:
            parts.append(_segment(segment) + ("" if last else "/"))
    return re.compile("".join(parts))


class Matcher:
    """Which paths of a repository are served: those `include` takes (all, when it's not given), minus `exclude`."""

    def __init__(self, include: Iterable[str] | None = None, exclude: Iterable[str] = ()):
        self._include = [compile_pattern(p) for p in include] if include is not None else None
        self._exclude = [compile_pattern(p) for p in exclude]

    @property
    def takes_everything(self) -> bool:
        return self._include is None and not self._exclude

    @staticmethod
    def _hits(patterns: list[re.Pattern[str]], path: str) -> bool:
        parts = path.split("/")
        candidates = ["/".join(parts[: i + 1]) for i in range(len(parts))]
        return any(p.fullmatch(c) for p in patterns for c in candidates)

    def allows(self, path: str) -> bool:
        """Whether a file at this path is served."""
        if self._include is not None and not self._hits(self._include, path):
            return False
        return not self._hits(self._exclude, path)


def under(path: str, folder: str) -> bool:
    """Whether a path is the folder itself or inside it (the root, `""`, holds everything)."""
    return not folder or path == folder or path.startswith(folder + "/")
