"""Made-up remote repositories for the mirror tests — no network: served over `file://`, or over HTTP on 127.0.0.1 by
git's own `http-backend`, which can ask for a token and redirect elsewhere.
"""

from __future__ import annotations

import base64
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from repos import git


def make_remote(source: Path, remote: Path) -> Path:
    """A bare copy of a made-up repository that serves partial clones, as the hosts do."""
    remote.parent.mkdir(parents=True, exist_ok=True)
    git(remote.parent, "clone", "-q", "--bare", "--no-local", str(source), str(remote))  # what is reachable, only
    git(remote, "config", "uploadpack.allowFilter", "true")
    return remote


def blobs_in(git_dir: Path) -> set[str]:
    """The file contents a repository holds."""
    out = git(git_dir, "cat-file", "--batch-all-objects", "--batch-check=%(objectname) %(objecttype)")
    return {line.split(" ")[0] for line in out.splitlines() if line.endswith(" blob")}


def contents_by_path(git_dir: Path) -> set[tuple[str, str]]:
    """Every (contents, path) pair in any commit of a repository."""
    pairs = set()
    for commit in git(git_dir, "rev-list", "--all").split():
        for line in git(git_dir, "ls-tree", "-r", commit).splitlines():
            meta, path = line.split("\t", 1)
            mode, kind, oid = meta.split(" ")
            if kind == "blob":
                pairs.add((oid, path))
    return pairs


class GitHTTP:
    """A smart-HTTP git server on 127.0.0.1 for the repositories under `root`. With `token`, every request must carry
    it as Basic credentials (any other answer is a 401); with `redirect_to`, the first request is sent to that server
    instead. It records every `Authorization` header it sees."""

    def __init__(self, root: Path, token: str | None = None, user: str = "x-access-token"):
        self.root = root
        self.expected = f"Basic {base64.b64encode(f'{user}:{token}'.encode()).decode()}" if token else None
        self.redirect_to: str | None = None
        self.seen: list[str] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *args):  # quiet
                pass

            def do_GET(self):
                server.handle(self)

            def do_POST(self):
                server.handle(self)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def url(self, name: str) -> str:
        return f"{self.base}/{name}"

    def __enter__(self) -> GitHTTP:
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def handle(self, request: BaseHTTPRequestHandler) -> None:
        auth = request.headers.get("Authorization")
        if auth:
            self.seen.append(auth)
        parts = urlsplit(request.path)
        if self.redirect_to and parts.path.endswith("/info/refs"):
            request.send_response(302)
            request.send_header("Location", self.redirect_to + request.path)
            request.end_headers()
            return
        if self.expected and auth != self.expected:
            request.send_response(401)
            request.send_header("WWW-Authenticate", 'Basic realm="made-up"')
            request.end_headers()
            return
        body = self._body(request)
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_PROJECT_ROOT=str(self.root),
            GIT_HTTP_EXPORT_ALL="1",
            PATH_INFO=parts.path,
            QUERY_STRING=parts.query,
            REQUEST_METHOD=request.command,
            CONTENT_TYPE=request.headers.get("Content-Type", ""),
            CONTENT_LENGTH=str(len(body)),
            REMOTE_ADDR="127.0.0.1",
        )
        if request.headers.get("Git-Protocol"):
            env["GIT_PROTOCOL"] = request.headers["Git-Protocol"]
        if request.headers.get("Content-Encoding"):
            env["HTTP_CONTENT_ENCODING"] = request.headers["Content-Encoding"]
        done = subprocess.run(["git", "http-backend"], input=body, env=env, capture_output=True, check=False)
        head, _, payload = done.stdout.partition(b"\r\n\r\n")
        if not _ and b"\n\n" in done.stdout:
            head, _, payload = done.stdout.partition(b"\n\n")
        status, headers = 200, []
        for line in head.decode("latin-1").splitlines():
            key, _, value = line.partition(":")
            if key.lower() == "status":
                status = int(value.strip().split(" ")[0])
            elif key:
                headers.append((key, value.strip()))
        request.send_response(status)
        for key, value in headers:
            request.send_header(key, value)
        request.end_headers()
        request.wfile.write(payload)

    @staticmethod
    def _body(request: BaseHTTPRequestHandler) -> bytes:
        if request.headers.get("Transfer-Encoding", "").lower() == "chunked":
            chunks = []
            while True:
                size = int(request.rfile.readline().strip().split(b";")[0], 16)
                if size == 0:
                    request.rfile.readline()
                    return b"".join(chunks)
                chunks.append(request.rfile.read(size))
                request.rfile.readline()
        length = int(request.headers.get("Content-Length") or 0)
        return request.rfile.read(length) if length else b""
