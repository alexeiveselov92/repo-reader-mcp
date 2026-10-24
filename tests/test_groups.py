"""Groups of repositories: the host's listing, taken by a pattern, made into mirrors — and kept in step with the host
(new repositories join, archived ones leave). The host is made up (tests/remotes.py): its API and its repositories on
127.0.0.1, no network.
"""

import base64
import json
from pathlib import Path

import pytest
from conftest import ask
from remotes import GitHTTP, make_remote
from repos import ADA, commit, git, write

from repo_reader_mcp.catalog import Catalog, listing_file
from repo_reader_mcp.config import Config, parse_config
from repo_reader_mcp.server import main, sync_once

pytestmark = pytest.mark.anyio

TOKEN = "made-up-token-4f1d2c"
ORG = "/api/v3/orgs/acme/repos"


def hosted(root: Path, path: str, files: dict[str, str] | None = None) -> Path:
    """A made-up repository at `path` (`acme/shop-api`) on the host serving `root`."""
    work = root.parent / "work" / path
    work.mkdir(parents=True)
    git(work, "init", "-q", "-b", "main")
    for name, text in (files or {"README.md": f"# {path}\n"}).items():
        write(work, name, text)
    commit(work, f"start {path}", ADA, "2026-01-01T09:00:00+00:00")
    return make_remote(work, root / f"{path}.git")


def github_item(path: str, description: str | None = None, archived: bool = False, **more) -> dict:
    return {"full_name": path, "description": description, "archived": archived, **more}


def grouped(host: GitHTTP, folder: Path, entry: dict, *others: dict) -> Config:
    data = {
        "repositories": [*others, {"host": host.base, **entry}],
        "mirrors": {"folder": str(folder)},
    }
    return parse_config(data, folder.parent)


@pytest.fixture
def host(tmp_path, monkeypatch):
    """A host with acme's repositories: two the pattern takes, one skipped, one archived, one it doesn't take."""
    monkeypatch.setenv("ACME_TOKEN", TOKEN)
    root = tmp_path / "host"
    for path in ("acme/shop-api", "acme/shop-web", "acme/shop-sandbox", "acme/shop-old", "acme/billing"):
        hosted(root, path, {"README.md": f"# {path}\n", "src/app.py": "print('hi')\n", "keys/prod.pem": "secret\n"})
    with GitHTTP(root, token=TOKEN) as server:
        server.api[ORG] = [
            github_item("acme/shop-api", "The shop's API."),
            github_item("acme/shop-web", clone_url="https://elsewhere.example.com/acme/shop-web.git"),
            github_item("acme/shop-sandbox"),
            github_item("acme/shop-old", archived=True),
            github_item("acme/billing"),
        ]
        yield server


GROUP = {"github": "acme/shop-*", "token_env": "ACME_TOKEN", "skip": ["shop-sandbox"], "exclude": ["*.pem"]}


async def test_a_group_serves_what_the_host_lists(host, tmp_path):
    config = grouped(host, tmp_path / "mirrors", GROUP)
    catalog = Catalog(config)
    assert list(catalog) == []  # never listed: nothing yet
    assert sync_once(config)
    catalog = Catalog(config)  # a new process: the listing kept on disk
    assert list(catalog) == ["shop-api", "shop-web"]
    api = catalog["shop-api"]
    assert api.config.description == "The shop's API."
    # Addresses are built from the host and the path, never taken from the listing (`clone_url` points elsewhere).
    assert catalog["shop-web"].mirror.remote.url == f"{host.base}/acme/shop-web.git"
    text, error = await ask(config, "list_repos")
    assert not error and "## shop-api" in text and "## shop-web" in text and "billing" not in text
    assert f"(one of `github: acme/shop-* on 127.0.0.1:{host.httpd.server_address[1]}`)" in text
    text, error = await ask(config, "read_file", repo="shop-api", path="src/app.py")
    assert not error and "print('hi')" in text
    text, error = await ask(config, "read_file", repo="shop-api", path="keys/prod.pem")  # the entry's exclude
    assert error and "outside what this server serves" in text
    kept = json.loads(listing_file(config.mirrors_folder, config.groups[0]).read_text())
    assert [m["name"] for m in kept["members"]] == ["shop-api", "shop-web"]
    assert sorted(kept["left_out"]) == ["acme/shop-old: archived", "acme/shop-sandbox: skipped"]


async def test_new_repositories_join_and_archived_ones_leave(host, tmp_path):
    config = grouped(host, tmp_path / "mirrors", GROUP)
    catalog = Catalog(config)
    ((group, outcome, worked),) = catalog.refresh()
    assert worked and outcome == "2 repositories; left out: 2"
    hosted(Path(host.root), "acme/shop-new")
    host.api[ORG] = [
        github_item("acme/shop-api"),
        github_item("acme/shop-web", archived=True),
        github_item("acme/shop-new"),
    ]
    ((group, outcome, worked),) = catalog.refresh()
    assert worked and outcome == "2 repositories; joined: shop-new; left: shop-web; left out: 1"
    assert list(catalog) == ["shop-api", "shop-new"]
    from repo_reader_mcp.mirror import sync_all

    sync_all(catalog.mirrors())
    from mcp import Client

    from repo_reader_mcp.server import build_server

    async with Client(build_server(config, catalog)) as client:
        found = await client.call_tool("read_file", {"repo": "shop-new", "path": "README.md"})
        assert not found.is_error and "acme/shop-new" in found.content[0].text
        gone = await client.call_tool("list_files", {"repo": "shop-web"})
        assert gone.is_error and "no repository named `shop-web`" in gone.content[0].text


def test_a_failed_listing_keeps_the_members_it_had(host, tmp_path):
    config = grouped(host, tmp_path / "mirrors", GROUP)
    catalog = Catalog(config)
    catalog.refresh()
    host.api_status = 500
    ((group, outcome, worked),) = catalog.refresh()
    assert not worked and outcome.startswith(f"{host.base} answered 500")
    assert list(catalog) == ["shop-api", "shop-web"]
    kept = json.loads(listing_file(config.mirrors_folder, config.groups[0]).read_text())
    assert kept["error"] and [m["name"] for m in kept["members"]] == ["shop-api", "shop-web"]


def test_pages_are_followed_on_the_host_s_api_only(host, tmp_path):
    config = grouped(host, tmp_path / "mirrors", GROUP)
    host.api_page_size = 2
    catalog = Catalog(config)
    ((_, outcome, worked),) = catalog.refresh()
    assert worked and list(catalog) == ["shop-api", "shop-web"]
    assert sum(1 for path, _ in host.api_seen if path.startswith(ORG)) == 3  # five repositories, two a page
    host.api_seen.clear()
    with GitHTTP(Path(host.root)) as elsewhere:
        host.api_next = f"{elsewhere.base}/api/v3/orgs/acme/repos?page=2"
        ((_, outcome, worked),) = catalog.refresh()
        assert not worked and "points outside its API" in outcome
        assert elsewhere.api_seen == []  # nothing, and no token, went there


def test_the_token_goes_to_the_api_only_and_no_redirect_is_followed(host, tmp_path):
    config = grouped(host, tmp_path / "mirrors", GROUP)
    catalog = Catalog(config)
    with GitHTTP(Path(host.root)) as elsewhere:
        host.api_redirect = elsewhere.base
        ((_, outcome, worked),) = catalog.refresh()
        assert not worked and "redirect" in outcome and elsewhere.base in outcome
        assert elsewhere.api_seen == []
    host.api_redirect = None
    catalog.refresh()
    assert {auth for _, auth in host.api_seen} == {f"Bearer {TOKEN}"}


def test_the_token_never_shows(host, tmp_path, capsys):
    config = grouped(host, tmp_path / "mirrors", GROUP)
    host.api_status = 403  # its message echoes the header it was sent
    catalog = Catalog(config)
    ((_, outcome, _),) = catalog.refresh()
    assert "made-up failure for Bearer ***" in outcome and TOKEN not in outcome
    kept = listing_file(config.mirrors_folder, config.groups[0]).read_text()
    assert TOKEN not in kept
    host.api_status = None
    sync_once(config)
    out = capsys.readouterr().out
    assert TOKEN not in out
    for file in (tmp_path / "mirrors").rglob("*"):
        if file.is_file():
            assert TOKEN.encode() not in file.read_bytes(), file


def test_a_wrong_token_is_said(host, tmp_path, monkeypatch):
    monkeypatch.setenv("ACME_TOKEN", "not-it")
    ((_, outcome, worked),) = Catalog(grouped(host, tmp_path / "mirrors", GROUP)).refresh()
    assert not worked and "answered 401 — the token was refused: Bad credentials" in outcome


def test_a_name_listed_one_by_one_wins(host, tmp_path, capsys):
    own = make_remote(Path(host.root) / "acme" / "shop-api.git", tmp_path / "own" / "shop-api.git")
    config = grouped(host, tmp_path / "mirrors", GROUP, {"url": f"file://{own}"})
    sync_once(config)
    out = capsys.readouterr().out
    assert "acme/shop-api (github: acme/shop-*" in out and "the name `shop-api` is taken — left out" in out
    catalog = Catalog(config)
    assert catalog["shop-api"].config.group is None and catalog["shop-web"].config.group


def test_names_a_server_can_t_serve_are_left_out(host, tmp_path):
    host.api[ORG] = [
        github_item("acme/shop-api"),
        github_item("acme/shop-x?y"),
        github_item("acme/../shop-api"),
        github_item("acme/.shop-hidden"),
        github_item("other/shop-api"),
        {"full_name": 42},
        "not a repository",
    ]
    catalog = Catalog(grouped(host, tmp_path / "mirrors", {**GROUP, "github": "acme/*"}))
    ((_, outcome, worked),) = catalog.refresh()
    assert worked and list(catalog) == ["shop-api"]
    left = catalog.listings[0].left_out
    assert "acme/shop-x?y: its name can't name a repository here" in left


def test_a_user_s_repositories_and_their_own_private_ones(host, tmp_path):
    del host.api[ORG]  # acme is a user, not an organisation
    host.api["/api/v3/users/acme/repos"] = [github_item("acme/shop-api")]
    host.api["/api/v3/user/repos"] = [github_item("acme/shop-api"), github_item("acme/shop-private")]
    catalog = Catalog(grouped(host, tmp_path / "mirrors", GROUP))
    catalog.refresh()
    assert list(catalog) == ["shop-api"]  # the token is someone else's: the public listing
    host.api["/api/v3/user"] = {"login": "Acme"}
    catalog.refresh()
    assert list(catalog) == ["shop-api", "shop-private"]


def test_an_owner_the_host_doesn_t_have(host, tmp_path):
    del host.api[ORG]
    ((_, outcome, worked),) = Catalog(grouped(host, tmp_path / "mirrors", GROUP)).refresh()
    assert (
        not worked
        and outcome == f"127.0.0.1:{host.httpd.server_address[1]} has no organisation or user `acme` the token can see"
    )


def test_a_gitlab_group_with_its_subgroups(host, tmp_path):
    for path in ("acme/backend/svc-orders", "acme/backend/team/svc-payments", "acme/backend/team/tools"):
        hosted(Path(host.root), path)
    host.api["/api/v4/groups/acme%2Fbackend/projects"] = [
        {"path_with_namespace": "acme/backend/svc-orders", "description": "Orders."},
        {"path_with_namespace": "acme/backend/team/svc-payments"},
        {"path_with_namespace": "acme/backend/team/tools"},
        {"path_with_namespace": "acme/backend/svc-legacy", "archived": True},
        {"path_with_namespace": "acme/backend/../other/svc-x"},  # `..` would step out of the group
    ]
    host.expected = "Basic " + base64.b64encode(f"oauth2:{TOKEN}".encode()).decode()  # GitLab's user, by default
    entry = {"gitlab": "acme/backend/**/svc-*", "token_env": "ACME_TOKEN"}
    config = grouped(host, tmp_path / "mirrors", entry)
    assert sync_once(config)
    catalog = Catalog(config)
    assert list(catalog) == ["svc-orders", "svc-payments"]
    assert "acme/backend/../other/svc-x: its name can't name a repository here" in catalog.listings[0].left_out
    asked = [path for path, _ in host.api_seen if path.startswith("/api/v4/")]
    assert asked and all("include_subgroups=true" in path and "with_shared=false" in path for path in asked)
    assert catalog["svc-payments"].mirror.remote.url == f"{host.base}/acme/backend/team/svc-payments.git"
    assert catalog["svc-payments"].mirror.remote.token_user == "oauth2"


def test_check_lists_a_group_and_writes_nothing(host, tmp_path, capsys):
    file = tmp_path / "config.yaml"
    file.write_text(
        "repositories:\n"
        f"  - github: acme/shop-*\n    host: {host.base}\n    token_env: ACME_TOKEN\n    skip: [shop-sandbox]\n"
        f"mirrors:\n  folder: {tmp_path / 'mirrors'}\n"
    )
    main(["--config", str(file), "--check"])
    out = capsys.readouterr().out
    assert "it serves 1 group:" in out and "the host lists 2 repositories it takes:" in out
    assert "shop-api  acme/shop-api  (not mirrored yet)" in out and "left out: acme/shop-old: archived" in out
    assert not (tmp_path / "mirrors").exists()


def test_check_says_when_a_group_can_t_be_listed(host, tmp_path, capsys):
    host.api_status = 502
    file = tmp_path / "config.yaml"
    file.write_text(
        f"repositories:\n  - github: acme/shop-*\n    host: {host.base}\n    token_env: ACME_TOKEN\n"
        f"mirrors:\n  folder: {tmp_path / 'mirrors'}\n"
    )
    main(["--config", str(file), "--check"])
    assert "host: can't list it:" in capsys.readouterr().out


# --- the refuting review's findings ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        lambda auth: f"HTTP/1.1 2x0 {auth}\r\n\r\n".encode(),  # not HTTP — and echoing the header it was sent
        lambda auth: b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n" + b"[" * 100_000,  # too deep
    ],
)
def test_an_answer_that_is_not_http_or_json_fails_the_listing_only(host, tmp_path, answer):
    def raw(request, auth):
        request.wfile.write(answer(auth))

    host.api_raw = raw
    catalog = Catalog(grouped(host, tmp_path / "mirrors", GROUP))
    ((_, outcome, worked),) = catalog.refresh()
    assert not worked and TOKEN not in outcome


def test_a_round_that_fails_never_ends_the_sync(host, tmp_path, monkeypatch, caplog):
    import repo_reader_mcp.catalog as catalog_module

    def broken(catalog):
        raise RuntimeError(f"made up, with {TOKEN} in it")

    monkeypatch.setattr(catalog_module, "sync_round", broken)
    catalog = Catalog(grouped(host, tmp_path / "mirrors", GROUP))
    with caplog.at_level("ERROR", logger="repo_reader_mcp"):
        catalog_module.keep_fresh(catalog, 0).join(5)
    assert "a sync round failed: RuntimeError: made up, with *** in it" in caplog.text and TOKEN not in caplog.text


def test_a_listing_sent_a_byte_at_a_time_is_stopped(host, tmp_path, monkeypatch):
    import time

    import repo_reader_mcp.hosts as hosts

    monkeypatch.setattr(hosts, "PAGE_SECONDS", 1)

    def drip(request, auth):
        request.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n")
        for _ in range(30):
            request.wfile.write(b" ")
            request.wfile.flush()
            time.sleep(0.1)

    host.api_raw = drip
    ((_, outcome, worked),) = Catalog(grouped(host, tmp_path / "mirrors", GROUP)).refresh()
    assert not worked and "took longer than 1 seconds" in outcome


def test_a_repository_listed_one_by_one_is_not_served_twice(host, tmp_path, capsys):
    """Its own entry's exclude would not hold for a second copy under the group's settings."""
    own = {"name": "api", "url": f"{host.base}/ACME/shop-api", "token_env": "ACME_TOKEN", "exclude": ["src"]}
    config = grouped(host, tmp_path / "mirrors", {**GROUP, "exclude": []}, own)
    sync_once(config)
    assert "acme/shop-api (github: acme/shop-*" in capsys.readouterr().out
    catalog = Catalog(config)
    assert sorted(catalog) == ["api", "shop-web"]
    assert "acme/shop-api" in catalog.clashes[0] and "already served as `api`" in catalog.clashes[0]


def test_an_environment_s_proxy_never_sees_a_token_sent_over_http(host, tmp_path, monkeypatch):
    with GitHTTP(Path(host.root)) as proxy:
        for name in ("no_proxy", "NO_PROXY"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("http_proxy", proxy.base)
        ((_, outcome, worked),) = Catalog(grouped(host, tmp_path / "mirrors", GROUP)).refresh()
        assert worked and proxy.api_seen == []


async def test_a_refresh_during_a_call_doesn_t_break_it(host, tmp_path, monkeypatch):
    from mcp import Client

    import repo_reader_mcp.guidance as guidance
    from repo_reader_mcp.server import build_server

    config = grouped(host, tmp_path / "mirrors", GROUP)
    sync_once(config)
    catalog = Catalog(config)
    due = guidance.Guide.due

    def refreshed_meanwhile(self, name, path):
        catalog._current = {}  # the group's repositories gone, between the call's start and its guidance
        return due(self, name, path)

    monkeypatch.setattr(guidance.Guide, "due", refreshed_meanwhile)
    async with Client(build_server(config, catalog)) as client:
        found = await client.call_tool("read_file", {"repo": "shop-api", "path": "README.md"})
    assert not found.is_error and "# acme/shop-api" in found.content[0].text


def test_a_kept_listing_is_checked_again_when_read(host, tmp_path):
    config = grouped(host, tmp_path / "mirrors", GROUP)
    file = listing_file(config.mirrors_folder, config.groups[0])
    file.parent.mkdir(parents=True)
    members = [
        {"name": "shop-api", "path": "acme/shop-api"},
        {"name": "payroll", "path": "other-org/payroll"},  # not acme's
        {"name": "shop-sandbox", "path": "acme/shop-sandbox"},  # skipped
        {"name": "renamed", "path": "acme/shop-web"},  # not its own name
    ]
    file.write_text(json.dumps({"members": members}))
    assert list(Catalog(config)) == ["shop-api"]


def test_a_next_page_can_t_step_out_of_the_api(host, tmp_path):
    host.api_page_size = 2
    host.api_next = f"{host.base}/api/v3/../../admin/x?page=2"
    ((_, outcome, worked),) = Catalog(grouped(host, tmp_path / "mirrors", GROUP)).refresh()
    assert not worked and "points outside its API" in outcome
    host.api_page_size = 3  # two pages: the second is the last
    host.api_next = f"HTTP://127.0.0.1:{host.httpd.server_address[1]}{ORG}?per_page=100&page=2"  # the same, spelt so
    ((_, outcome, worked),) = Catalog(grouped(host, tmp_path / "mirrors", GROUP)).refresh()
    assert worked


# --- links to the host's own pages ----------------------------------------------------------------------------------


async def test_answers_link_to_the_host_s_pages(host, tmp_path):
    config = grouped(host, tmp_path / "mirrors", GROUP)
    sync_once(config)
    page = f"{host.base}/acme/shop-api"
    commit = git(Path(host.root) / "acme" / "shop-api.git", "rev-parse", "HEAD")
    expected = {
        ("list_repos", ()): f"On GitHub: {page}\n",
        ("read_file", (("path", "src/app.py"),)): f"On GitHub: {page}/blob/{commit}/src/app.py#L1\n",
        ("blame", (("path", "src/app.py"),)): f"On GitHub: {page}/blob/{commit}/src/app.py#L1\n",
        ("list_files", (("path", "src"),)): f"On GitHub: {page}/tree/{commit}/src\n",
        ("show_commit", (("commit", "main"),)): f"On GitHub: {page}/commit/{commit}\n",
        ("diff", (("base", "main"), ("head", "main"))): f"On GitHub: {page}/compare/{commit}...{commit}\n",
    }
    for (tool, arguments), line in expected.items():
        repo = {} if tool == "list_repos" else {"repo": "shop-api"}
        text, error = await ask(config, tool, **repo, **dict(arguments))
        assert not error and line in text, (tool, text)


async def test_links_say_their_kind_or_are_turned_off(host, tmp_path, shop):
    config = grouped(host, tmp_path / "mirrors", {**GROUP, "links": "gitlab"})
    sync_once(config)
    text, _ = await ask(config, "read_file", repo="shop-api", path="src/app.py")
    assert f"On GitLab: {host.base}/acme/shop-api/-/blob/" in text
    config = grouped(host, tmp_path / "mirrors", {**GROUP, "links": "none"})
    text, _ = await ask(config, "list_repos")
    assert "On GitHub" not in text and "On GitLab" not in text
    with pytest.raises(Exception, match="links: it is for a remote repository"):
        parse_config({"repositories": [{"name": "shop", "path": str(shop[0]), "links": "github"}]}, tmp_path)


# --- forks, and names two repositories of a group share -------------------------------------------------------------


def test_forks_are_left_out_unless_asked_for(host, tmp_path):
    host.api[ORG] = [github_item("acme/shop-api"), github_item("acme/shop-redis", fork=True)]
    catalog = Catalog(grouped(host, tmp_path / "mirrors", GROUP))
    catalog.refresh()
    assert list(catalog) == ["shop-api"]
    assert catalog.listings[0].left_out == ("acme/shop-redis: a fork (`forks: true` takes forks)",)
    catalog = Catalog(grouped(host, tmp_path / "mirrors", {**GROUP, "forks": True}))
    catalog.refresh()
    assert list(catalog) == ["shop-api", "shop-redis"]


def test_repositories_of_a_gitlab_group_that_share_a_name_are_all_served(host, tmp_path):
    host.api["/api/v4/groups/acme%2Fbackend/projects"] = [
        {"path_with_namespace": "acme/backend/api"},
        {"path_with_namespace": "acme/backend/legacy/api"},
        {"path_with_namespace": "acme/backend/team/svc"},
        {"path_with_namespace": "acme/backend/team/upstream-lib", "forked_from_project": {"id": 7}},
    ]
    config = grouped(host, tmp_path / "mirrors", {"gitlab": "acme/backend/**", "token_env": "ACME_TOKEN"})
    catalog = Catalog(config)
    catalog.refresh()
    assert list(catalog) == ["api", "legacy.api", "svc"]  # each of the two `api` by its path below the group
    assert catalog["legacy.api"].mirror.remote.url == f"{host.base}/acme/backend/legacy/api.git"
    assert "acme/backend/team/upstream-lib: a fork (`forks: true` takes forks)" in catalog.listings[0].left_out
    assert list(Catalog(config)) == ["api", "legacy.api", "svc"]  # the kept listing, read again at a restart
