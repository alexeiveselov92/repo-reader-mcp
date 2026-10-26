"""Streamable HTTP: a shared server behind a bearer token — a real server on 127.0.0.1, answered by the SDK's own client
and by plain HTTP requests (string JSON-RPC ids, as gateways send them) — and `/health`, the one path a probe reaches
without the token.
"""

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager

import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from remotes import make_remote

from repo_reader_mcp.catalog import Catalog, keep_fresh
from repo_reader_mcp.config import ConfigError, parse_config
from repo_reader_mcp.server import _address, build_server, http_app

pytestmark = pytest.mark.anyio

TOKEN = "made-up-bearer-9c41"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@contextmanager
def serving(app):
    """The app served on 127.0.0.1 in a thread; its MCP address."""
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        thread.join(5)


def guarded(shop_path, monkeypatch, **http):
    monkeypatch.setenv("MCP_TOKEN", TOKEN)
    data = {"repositories": [{"name": "shop", "path": str(shop_path)}], "http": http or {"token_env": "MCP_TOKEN"}}
    config = parse_config(data, shop_path.parent)
    return config, http_app(build_server(config), config, "127.0.0.1")


def post(url: str, message: dict, headers: dict[str, str]) -> tuple[int, dict, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(message).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, _json(response.read()), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, _json(error.read()), dict(error.headers)


def get(url: str, method: str = "GET") -> tuple[int, bytes]:
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _json(body: bytes) -> dict:
    try:
        return json.loads(body or b"{}")
    except ValueError:
        return {"text": body.decode(errors="replace")}


INITIALIZE = {
    "jsonrpc": "2.0",
    "id": "gateway-7f",
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "made-up", "version": "1"}},
}


async def test_a_client_reads_over_http_with_the_token(shop, monkeypatch):
    _, app = guarded(shop[0], monkeypatch)
    with serving(app) as url:
        http = create_mcp_http_client(headers={"Authorization": f"Bearer {TOKEN}"})
        async with Client(streamable_http_client(url, http_client=http)) as client:
            listed = await client.call_tool("list_repos", {})
            read = await client.call_tool("read_file", {"repo": "shop", "path": "README.md"})
    assert not listed.is_error and "## shop" in listed.content[0].text
    assert not read.is_error and "README.md" in read.content[0].text


def test_no_token_or_a_wrong_one_is_refused(shop, monkeypatch):
    _, app = guarded(shop[0], monkeypatch)
    with serving(app) as url:
        for headers in ({}, {"Authorization": "Bearer not-it"}, {"Authorization": TOKEN}):
            status, body, answer_headers = post(url, INITIALIZE, headers)
            assert status == 401 and "result" not in body, headers
            assert answer_headers.get("www-authenticate", answer_headers.get("WWW-Authenticate", "")).startswith(
                "Bearer"
            )


def test_string_ids_are_answered_as_given(shop, monkeypatch):
    _, app = guarded(shop[0], monkeypatch)
    with serving(app) as url:
        status, body, _ = post(url, INITIALIZE, {"Authorization": f"Bearer {TOKEN}"})
    assert status == 200 and body["id"] == "gateway-7f" and body["result"]["serverInfo"]["name"] == "repo-reader-mcp"


def test_an_open_address_needs_a_token_or_a_gateway(shop, monkeypatch):
    path = shop[0]
    open_config = parse_config({"repositories": [{"name": "shop", "path": str(path)}]}, path.parent)
    with pytest.raises(ConfigError) as caught:
        http_app(build_server(open_config), open_config, "0.0.0.0")
    assert "lets anyone who reaches it read the code" in str(caught.value)
    http_app(build_server(open_config), open_config, "127.0.0.1")  # one person's machine: no token needed
    gateway = parse_config(
        {"repositories": [{"name": "shop", "path": str(path)}], "http": {"behind_gateway": True}}, path.parent
    )
    http_app(build_server(gateway), gateway, "0.0.0.0")


def test_http_settings_are_checked(shop, monkeypatch):
    path = shop[0]
    monkeypatch.setenv("MCP_TOKEN", TOKEN)
    repos = [{"name": "shop", "path": str(path)}]
    for http, says in [
        ({"token_env": "MCP_TOKEN", "behind_gateway": True}, "not both"),
        ({"token_env": "UNSET_MADE_UP"}, "the variable UNSET_MADE_UP is not set"),
        ({"token_env": "Bearer abc"}, "never the token itself"),
    ]:
        with pytest.raises(ConfigError) as caught:
            parse_config({"repositories": repos, "http": http}, path.parent)
        assert says in caught.value.problems[0], (http, caught.value.problems)


def test_the_address_to_serve_on():
    assert _address("8000") == ("127.0.0.1", 8000)
    assert _address("0.0.0.0:9000") == ("0.0.0.0", 9000)
    assert _address("[::1]:8000") == ("::1", 8000)
    for wrong in ("abc", "host:", "host:70000"):
        with pytest.raises(Exception, match="is not"):
            _address(wrong)


def test_on_the_machine_s_own_address_only_its_own_name_is_answered(shop):
    """No token on 127.0.0.1 — so a web page must not reach it through a domain name that resolves there."""
    path = shop[0]
    config = parse_config({"repositories": [{"name": "shop", "path": str(path)}]}, path.parent)
    with serving(http_app(build_server(config), config, "127.0.0.1")) as url:
        status, body, _ = post(url, INITIALIZE, {})
        assert status == 200 and body["id"] == "gateway-7f"
        status, body, _ = post(url, INITIALIZE, {"Host": "attacker.example.com"})
        assert status >= 400 and "result" not in body


def test_another_loopback_address_is_not_the_machine_s_own(shop):
    """Only the addresses the SDK guards against DNS rebinding serve with no token."""
    path = shop[0]
    config = parse_config({"repositories": [{"name": "shop", "path": str(path)}]}, path.parent)
    for host in ("127.0.0.2", "127.1.2.3", "0.0.0.0", "::"):
        with pytest.raises(ConfigError):
            http_app(build_server(config), config, host)


def test_a_proxy_on_the_same_machine_is_answered(shop, monkeypatch):
    """Guarded by a token, the server answers whatever host name a reverse proxy forwards."""
    _, app = guarded(shop[0], monkeypatch)
    with serving(app) as url:
        status, body, _ = post(url, INITIALIZE, {"Authorization": f"Bearer {TOKEN}", "Host": "code.example.com"})
    assert status == 200 and body["id"] == "gateway-7f"


def get_at_once(url: str, headers: dict[str, str]) -> tuple[int, dict, bytes | None, float]:
    """A GET given 3 seconds: its status, its headers, its body (None when it didn't come in time) and the seconds it
    took. A stream held open is a slow answer here, never a hang."""
    start = time.monotonic()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=3) as response:
            status, answer_headers = response.status, response.headers
            try:
                body = response.read()
            except TimeoutError:
                body = None
    except urllib.error.HTTPError as error:
        status, answer_headers, body = error.code, error.headers, error.read()
    except (TimeoutError, urllib.error.URLError):
        status, answer_headers, body = 0, {}, None
    return status, {key.lower(): value for key, value in answer_headers.items()}, body, time.monotonic() - start


@pytest.mark.parametrize("http", [{"token_env": "MCP_TOKEN"}, {"behind_gateway": True}])
def test_a_get_of_mcp_is_answered_405_at_once(shop, monkeypatch, http):
    """Streamable HTTP's GET opens a stream for the server's own messages; this server has none, and says so at once
    instead of holding an empty stream open — a gateway in front would wait on it."""
    _, app = guarded(shop[0], monkeypatch, **http)
    token = {"Authorization": f"Bearer {TOKEN}"}
    with serving(app) as url:
        for path, accept in [(url, "text/event-stream"), (url, "*/*"), (url + "/", "text/event-stream")]:
            status, headers, body, seconds = get_at_once(path, {**token, "Accept": accept})
            assert (status, seconds < 1) == (405, True), (path, accept, status, round(seconds, 2))
            assert headers["allow"] == "POST" and headers["content-type"] == "application/json"
            assert "stateless" in json.loads(body)["error"] and "POST" in json.loads(body)["error"]
        assert get_at_once(url + "x", token)[0] == 404  # another path is not the MCP path
        status, body, _ = post(url, INITIALIZE, token)  # POST still answers
        assert status == 200 and body["result"]["serverInfo"]["name"] == "repo-reader-mcp"
        listing = {"jsonrpc": "2.0", "id": "list-1", "method": "tools/list", "params": {}}
        status, body, _ = post(url, listing, {**token, "MCP-Protocol-Version": "2025-06-18"})
        assert status == 200 and "read_file" in {tool["name"] for tool in body["result"]["tools"]}


def test_a_get_of_mcp_without_the_token_is_401_and_nothing_else(shop, monkeypatch):
    """The token stays outermost: before it, nothing — not even that the server offers no stream — is answered."""
    _, app = guarded(shop[0], monkeypatch)
    with serving(app) as url:
        for headers in ({}, {"Authorization": "Bearer not-it"}):
            for path in (url, url + "/"):
                status, answer, body, seconds = get_at_once(path, {**headers, "Accept": "text/event-stream"})
                assert (status, seconds < 1) == (401, True), (path, headers, status)
                assert answer["www-authenticate"].startswith("Bearer") and "allow" not in answer
                assert json.loads(body) == {"error": "a bearer token is needed"}


def test_health_is_answered_without_the_token_and_says_nothing_else(shop, monkeypatch):
    _, app = guarded(shop[0], monkeypatch)
    with serving(app) as url:
        status, body = get(url.replace("/mcp", "/health"))
        head, _ = get(url.replace("/mcp", "/health"), "HEAD")
    assert status == 200 and head == 200
    assert json.loads(body) == {"status": "ready"}


def test_only_health_itself_passes_without_the_token(shop, monkeypatch):
    _, app = guarded(shop[0], monkeypatch)
    with serving(app) as url:
        root = url.removesuffix("/mcp")
        for path in ("/health/", "/healthz", "/Health", "/health/../mcp", "/mcp/health", "/"):
            assert get(root + path)[0] == 401, path
        status, body, _ = post(root + "/health", INITIALIZE, {})  # MCP sent to /health reaches no tool
        assert status == 405 and "result" not in body
        status, body, _ = post(url, {**INITIALIZE, "id": "/health"}, {})
        assert status == 401 and "result" not in body


@pytest.fixture
def unsynced(shop, tmp_path):
    """A configuration mirroring the shop from a made-up remote, never synced yet; its mirrors' folder."""
    remote = make_remote(shop[0], tmp_path / "remotes" / "shop.git")
    folder = tmp_path / "mirrors"
    data = {
        "repositories": [{"name": "shop", "url": f"file://{remote}"}],
        "mirrors": {"folder": str(folder)},
        "http": {"behind_gateway": True},
    }
    return parse_config(data, tmp_path)


def test_health_waits_for_the_first_sync(unsynced):
    catalog = Catalog(unsynced)
    with serving(http_app(build_server(unsynced, catalog), unsynced, "127.0.0.1")) as url:
        health = url.replace("/mcp", "/health")
        status, body = get(health)
        assert status == 503 and json.loads(body) == {"status": "syncing"}  # no repository named
        keep_fresh(catalog, 0).join(30)
        status, body = get(health)
    assert status == 200 and json.loads(body) == {"status": "ready"}


def test_a_restart_over_kept_mirrors_is_ready_at_once(unsynced):
    keep_fresh(Catalog(unsynced), 0).join(30)
    assert Catalog(unsynced).ready.is_set()  # a new process, the mirrors' folder kept: no round has run in it


def test_a_first_round_that_fails_still_ends_the_wait(tmp_path):
    data = {"repositories": [{"name": "shop", "url": f"file://{tmp_path}/nowhere.git"}]}
    catalog = Catalog(parse_config({**data, "mirrors": {"folder": str(tmp_path / "mirrors")}}, tmp_path))
    assert not catalog.ready.is_set()
    keep_fresh(catalog, 0).join(30)
    assert catalog.ready.is_set() and not catalog.mirrors()[0].ready  # served as it is: its tools say it isn't made


def test_local_repositories_are_ready_at_once(shop):
    path = shop[0]
    assert Catalog(parse_config({"repositories": [{"name": "shop", "path": str(path)}]}, path.parent)).ready.is_set()


def test_probes_are_left_out_of_the_access_log():
    import logging

    from repo_reader_mcp.server import QuietProbes

    def line(path: str, method: str = "GET") -> logging.LogRecord:  # as uvicorn's access log makes one
        args = ("10.0.0.7:5100", method, path, "1.1", 200)
        return logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d', args, None)

    quiet = QuietProbes()
    assert not quiet.filter(line("/health")) and not quiet.filter(line("/health", "HEAD"))
    assert quiet.filter(line("/mcp")) and quiet.filter(line("/health?x=1")) and quiet.filter(line("/healthz"))
    assert quiet.filter(line("/health", "POST")) and quiet.filter(line("/health", "DELETE"))  # not a probe: logged
