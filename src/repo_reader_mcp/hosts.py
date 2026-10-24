"""Code hosts with an API: the repositories of an owner, listed for a group (docs/remote-repositories.md, "Groups").

Only reading requests (`GET`), to the host's API alone: a redirect is never followed, and a next page that points
anywhere else is refused — a token travels with them. Repositories are fetched from addresses this server builds from
the host and a repository's path, never from addresses an answer gives.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from . import __version__

GITHUB, GITLAB = "github", "gitlab"
PUBLIC = {GITHUB: "github.com", GITLAB: "gitlab.com"}
TOKEN_USER = {GITHUB: "x-access-token", GITLAB: "oauth2"}  # what git sends as the user beside a token
PAGE_SIZE = 100
MAX_PAGES = 200  # 20,000 repositories
PAGE_BYTES = 32 * 1024 * 1024
TIMEOUT_SECONDS = 30  # one wait for the host
PAGE_SECONDS = 60  # one page, read whole — a host sending it a byte at a time is stopped here
DEFAULT_PORTS = {"http": 80, "https": 443}


class HostError(Exception):
    """A host's listing could not be had; the message says why, with no token in it."""


class _NotFound(HostError):
    pass


@dataclass(frozen=True)
class Host:
    """A code host: where its repositories' pages and git addresses start, and where its API is."""

    kind: str
    web: str  # https://github.com
    api: str  # https://api.github.com

    @property
    def name(self) -> str:
        return urlsplit(self.web).netloc + urlsplit(self.web).path

    def git_url(self, path: str) -> str:
        return f"{self.web}/{path}.git"


def host_of(kind: str, host: str | None) -> Host:
    """GitHub or GitLab — the public one, or one at an address (`git.example.com`, `https://example.com/gitlab`)."""
    if not host:
        web = f"https://{PUBLIC[kind]}"
    elif "://" in host:
        web = host.rstrip("/")
    else:
        web = f"https://{host.strip('/')}"
    if kind == GITHUB:
        api = "https://api.github.com" if web == "https://github.com" else f"{web}/api/v3"
    else:
        api = f"{web}/api/v4"
    return Host(kind, web, api)


@dataclass(frozen=True)
class Listed:
    """A repository as a host lists it."""

    path: str  # acme/shop-api — for GitLab, the full path through its subgroups
    description: str | None
    archived: bool


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # not followed: the answer is the redirect, which `_get` turns into an error


def _opener(direct: bool) -> urllib.request.OpenerDirector:
    """Made for each request, so the environment's proxy settings are read as they are then. `direct`: through no
    proxy — for a token over plain http (to this machine only), which a proxy would read."""
    return urllib.request.build_opener(*([urllib.request.ProxyHandler({})] if direct else []), _NoRedirect)


def _message(body: bytes) -> str:
    try:
        data = json.loads(body)
    except ValueError:
        return ""
    if isinstance(data, dict):
        for key in ("message", "error_description", "error"):
            if isinstance(data.get(key), str):
                return data[key]
    return ""


def _origin(address: str) -> tuple[str, str, int | None]:
    parts = urlsplit(address)
    scheme = parts.scheme.lower()
    return scheme, (parts.hostname or "").lower(), parts.port or DEFAULT_PORTS.get(scheme)


def _next_page(link: str, api: str) -> str | None:
    """The next page from a `Link` header — refused when it points outside the host's API: another origin, another
    path, credentials, or a `.` / `..` part stepping out of it."""
    for part in link.split(","):
        address, _, params = part.partition(";")
        if 'rel="next"' not in params.replace(" ", ""):
            continue
        address = address.strip().removeprefix("<").removesuffix(">")
        there = urlsplit(address)
        try:
            same = _origin(address) == _origin(api) and there.username is None and there.password is None
        except ValueError:  # a port that is not one
            same = False
        steps = any(segment in (".", "..") for segment in unquote(there.path).split("/"))
        if not same or steps or not there.path.startswith(urlsplit(api).path + "/"):
            raise HostError(f"the host's next page points outside its API ({address}) — not followed")
        return address
    return None


def _get(url: str, token: str | None, api: str) -> tuple[Any, str | None]:
    """One page of JSON, and the address of the next one."""
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": f"repo-reader-mcp/{__version__}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    if token:
        request.add_unredirected_header("Authorization", f"Bearer {token}")
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(url))
    opener = _opener(direct=bool(token) and url.lower().startswith("http://"))
    deadline = time.monotonic() + PAGE_SECONDS
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            chunks, size = [], 0
            while chunk := response.read1(64 * 1024):
                chunks.append(chunk)
                size += len(chunk)
                if size > PAGE_BYTES:
                    raise HostError("a page of the host's listing is larger than the server reads")
                if time.monotonic() > deadline:
                    raise HostError(f"{origin} took longer than {PAGE_SECONDS} seconds to send a page of its listing")
            body = b"".join(chunks)
            link = response.headers.get("Link", "")
    except HostError:
        raise
    except urllib.error.HTTPError as error:
        try:
            message = _message(error.read1(64 * 1024))
        except Exception:  # an error's body that can't be read says nothing more
            message = ""
        if error.code == 404:
            raise _NotFound(message) from None
        if 300 <= error.code < 400:
            where = error.headers.get("Location", "elsewhere")
            raise HostError(
                f"{origin} answered with a redirect to {where} ({error.code}), which the server doesn't follow — "
                "a renamed owner is written in the configuration by its new name"
            ) from None
        refused = " — the token was refused" if error.code == 401 and token else ""
        raise HostError(f"{origin} answered {error.code}{refused}" + (f": {message}" if message else "")) from None
    except (urllib.error.URLError, OSError) as error:
        reason = getattr(error, "reason", None) or error
        raise HostError(f"can't reach {origin}: {reason}") from None
    except Exception as error:  # an answer that isn't HTTP (a broken status line, a header too long, …)
        raise HostError(f"{origin} answered something that is not HTTP: {type(error).__name__}: {error}") from None
    try:
        data = json.loads(body)
    except (ValueError, RecursionError):  # not JSON — or nested deeper than Python reads
        raise HostError(f"{origin} answered something that is not JSON a listing can be read from") from None
    return data, _next_page(link, api)


def _pages(url: str, token: str | None, api: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for _ in range(MAX_PAGES):
        data, url = _get(url, token, api)
        if not isinstance(data, list):
            raise HostError("the host's listing is not a list of repositories")
        items += [item for item in data if isinstance(item, dict)]
        if url is None:
            return items
    raise HostError(f"the host lists more than {MAX_PAGES * PAGE_SIZE} repositories for one owner")


def _text(value: Any) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def _github(host: Host, owner: str, token: str | None) -> list[Listed]:
    try:
        items = _pages(f"{host.api}/orgs/{quote(owner)}/repos?type=all&per_page={PAGE_SIZE}", token, host.api)
    except _NotFound:
        # Not an organisation: a user. The user's own token lists their private repositories as well.
        address = f"{host.api}/users/{quote(owner)}/repos?type=owner&per_page={PAGE_SIZE}"
        if token:
            try:
                me, _ = _get(f"{host.api}/user", token, host.api)
            except HostError:
                me = None
            if isinstance(me, dict) and str(me.get("login", "")).lower() == owner.lower():
                address = f"{host.api}/user/repos?affiliation=owner&visibility=all&per_page={PAGE_SIZE}"
        items = _pages(address, token, host.api)
    return [
        Listed(item["full_name"], _text(item.get("description")), bool(item.get("archived") or item.get("disabled")))
        for item in items
        if isinstance(item.get("full_name"), str)
    ]


def _gitlab(host: Host, owner: str, subgroups: bool, token: str | None) -> list[Listed]:
    query = f"archived=false&per_page={PAGE_SIZE}&order_by=path&sort=asc"
    try:
        items = _pages(
            f"{host.api}/groups/{quote(owner, safe='')}/projects?include_subgroups={str(subgroups).lower()}"
            f"&with_shared=false&{query}",
            token,
            host.api,
        )
    except _NotFound:
        if "/" in owner:
            raise
        items = _pages(f"{host.api}/users/{quote(owner, safe='')}/projects?{query}", token, host.api)
    return [
        Listed(item["path_with_namespace"], _text(item.get("description")), bool(item.get("archived")))
        for item in items
        if isinstance(item.get("path_with_namespace"), str)
    ]


def list_repositories(host: Host, owner: str, *, subgroups: bool = False, token: str | None = None) -> list[Listed]:
    """Every repository of an owner (a GitHub organisation or user; a GitLab group — with its subgroups when asked —
    or user) that the token, or the public, can see."""
    try:
        if host.kind == GITHUB:
            found = _github(host, owner, token)
        else:
            found = _gitlab(host, owner, subgroups, token)
    except _NotFound:
        kind = "organisation or user" if host.kind == GITHUB else "group or user"
        seen = "the token can see" if token else "visible without a token"
        raise HostError(f"{host.name} has no {kind} `{owner}` {seen}") from None
    except HostError as error:
        raise HostError(str(error).replace(token, "***") if token else str(error)) from None
    return found
