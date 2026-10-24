"""Links to a host's own pages for what an answer shows — a file at a commit and its lines, a folder, a commit, a
comparison — so an agent can hand people a link they open in their browser (docs/reference/tools.md).

Known for github.com, gitlab.com and bitbucket.org, for a group's host, and for any host whose kind the configuration
names (`links: gitlab`). A link is built from the repository's address and a commit id, never from an agent's text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

KINDS = ("github", "gitlab", "bitbucket")
LABELS = {"github": "GitHub", "gitlab": "GitLab", "bitbucket": "Bitbucket"}
KNOWN = {"github.com": "github", "gitlab.com": "gitlab", "bitbucket.org": "bitbucket"}
SCP_LIKE = re.compile(r"^(?:[^@/]+@)?(?P<host>[A-Za-z0-9][A-Za-z0-9.-]*):(?P<path>[^/].*)$")


@dataclass(frozen=True)
class Links:
    kind: str  # github | gitlab | bitbucket
    base: str  # https://github.com/acme/shop — the repository's page

    @property
    def label(self) -> str:
        return LABELS[self.kind]

    def _at(self, page: str, commit: str, path: str = "") -> str:
        where = f"/{quote(path, safe='/')}" if path else ""
        if self.kind == "gitlab":
            return f"{self.base}/-/{page}/{commit}{where}"
        if self.kind == "bitbucket":
            return f"{self.base}/src/{commit}{where}"
        return f"{self.base}/{page}/{commit}{where}"

    def file(self, commit: str, path: str, start: int | None = None, end: int | None = None) -> str:
        link = self._at("blob", commit, path)
        if start is None:
            return link
        end = end if end is not None and end > start else None
        if self.kind == "gitlab":
            return link + f"#L{start}" + (f"-{end}" if end else "")
        if self.kind == "bitbucket":
            return link + f"#lines-{start}" + (f":{end}" if end else "")
        return link + f"#L{start}" + (f"-L{end}" if end else "")

    def folder(self, commit: str, path: str = "") -> str:
        return self._at("tree", commit, path)

    def commit(self, commit: str) -> str:
        if self.kind == "gitlab":
            return f"{self.base}/-/commit/{commit}"
        if self.kind == "bitbucket":
            return f"{self.base}/commits/{commit}"
        return f"{self.base}/commit/{commit}"

    def compare(self, base: str, head: str) -> str | None:
        if self.kind == "gitlab":
            return f"{self.base}/-/compare/{base}...{head}"
        if self.kind == "github":
            return f"{self.base}/compare/{base}...{head}"
        return None  # Bitbucket's comparison pages take branch names, not commits


def links_for(url: str, kind: str | None = None) -> Links | None:
    """The host's pages for a repository fetched from `url` — the kind named, or known from the host's name; None when
    neither tells (or `kind` is `none`). Pages are at an http(s) URL's own address; for ssh, on https at the host."""
    if kind == "none":
        return None
    if "://" in url:
        parts = urlsplit(url)
        host, path = parts.hostname or "", parts.path
        origin = f"{parts.scheme}://{parts.netloc}" if parts.scheme in ("http", "https") else f"https://{host}"
        if parts.scheme == "file" or not host:
            return None
    else:
        found = SCP_LIKE.fullmatch(url)
        if not found:
            return None
        host, path = found["host"], found["path"]
        origin = f"https://{host}"
    kind = kind or KNOWN.get(host.lower())
    path = path.strip("/").removesuffix(".git")
    if kind not in KINDS or not path:
        return None
    return Links(kind, f"{origin}/{path}")
