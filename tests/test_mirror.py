"""Remote repositories, mirrored: made by the sync, kept in step with the host, read by every tool as a local repository
is — and holding the contents of served files only. The remotes are made up and served over `file://` (or HTTP on
127.0.0.1, in test_safety.py): no network.
"""

import os
import re
import threading
from pathlib import Path

import pytest
from conftest import ask, config_for
from remotes import blobs_in, contents_by_path, make_remote
from repos import ADA, ALAN, GRACE, commit, git, write

from repo_reader_mcp.config import Config, parse_config
from repo_reader_mcp.mirror import Mirror, SyncError
from repo_reader_mcp.paths import Matcher
from repo_reader_mcp.server import main

pytestmark = pytest.mark.anyio


@pytest.fixture
def remote(shop, tmp_path) -> Path:
    """A fresh bare copy of the made-up shop for each test, which the test may change as a host's repository changes."""
    return make_remote(shop[0], tmp_path / "remotes" / "shop.git")


def mirrored(url: str, folder: Path, **settings) -> Config:
    """A configuration mirroring one repository, named `shop`, into `folder`."""
    data = {"repositories": [{"name": "shop", "url": url, **settings}], "mirrors": {"folder": str(folder)}}
    return parse_config(data, folder.parent)


def mirror_of(config: Config) -> Mirror:
    return Mirror(config.repositories[0])


def push(remote: Path, work: Path, change: str, message: str, author=ALAN, date="2026-03-10T10:00:00+00:00") -> str:
    """A commit made in a clone and pushed to the remote's main, as a developer would."""
    if not work.exists():
        git(work.parent, "clone", "-q", str(remote), str(work))
    write(work, "src/shop/notes.py", change)
    sha = commit(work, message, author, date)
    git(work, "push", "-q", "origin", "main")
    return sha


# --- making a mirror ------------------------------------------------------------------------------------------------


def test_a_first_sync_makes_a_partial_mirror(remote, tmp_path):
    cfg = mirrored(f"file://{remote}", tmp_path / "mirrors", refs=["main"])
    mirror = mirror_of(cfg)
    assert not mirror.ready
    # 11: secrets/prod.env is named for credentials, so never fetched
    assert mirror.sync() == "mirrored for the first time — 1 branch, 0 tags, 11 files' contents"
    assert mirror.ready and mirror.git_dir.parent == tmp_path / "mirrors"
    # The whole history of main, but the contents of only the files at its tip.
    assert git(mirror.git_dir, "rev-list", "--count", "main") == git(remote, "rev-list", "--count", "main")
    listing = [line.split(None, 3) for line in git(remote, "ls-tree", "-r", "main").splitlines()]
    at_tip = {oid for _, _, oid, path in listing if not path.endswith(".env")}
    assert blobs_in(mirror.git_dir) == at_tip
    assert mirror.sync() == "up to date"


async def test_tools_read_a_mirror_as_they_read_the_repository_itself(remote, tmp_path):
    """Every reading tool answers the same about the mirror as about the repository it mirrors — older commits, whose
    contents the mirror fetches when they are first read, included."""
    cfg = mirrored(f"file://{remote}", tmp_path / "mirrors")
    mirror_of(cfg).sync()
    local = config_for(remote)
    for tool, arguments in [
        ("list_refs", {}),
        ("read_file", {"path": "src/shop/pricing.py"}),
        ("read_file", {"path": "src/shop/cart.py", "ref": "main~2"}),
        ("list_files", {"recursive": True, "ref": "v0.1"}),
        ("log", {"path": "src/shop/cart.py"}),
        ("show_commit", {"commit": "main~1"}),
        ("show_commit", {"commit": "v0.1"}),
        ("diff", {"base": "v0.1", "head": "feature/discounts", "since_fork": True}),
        ("blame", {"path": "src/shop/cart.py"}),
        ("blame", {"path": "src/shop/pricing.py", "ref": "feature/discounts"}),
    ]:
        expected, error = await ask(local, tool, repo="shop", **arguments)
        assert not error, (tool, expected)
        assert await ask(cfg, tool, repo="shop", **arguments) == (expected, False), tool


async def test_list_repos_says_where_a_mirror_comes_from_and_how_fresh_it_is(remote, tmp_path):
    cfg = mirrored(f"file://{remote}", tmp_path / "mirrors")
    mirror_of(cfg).sync()
    text, _ = await ask(cfg, "list_repos")
    assert f"Mirrored from file://{remote}, synced 20" in text and "UTC." in text


async def test_a_mirror_not_made_yet_says_so(remote, tmp_path):
    cfg = mirrored(f"file://{remote}", tmp_path / "mirrors")
    text, _ = await ask(cfg, "list_repos")
    assert "being mirrored" in text and "for the first time" in text
    text, error = await ask(cfg, "read_file", repo="shop", path="README.md")
    assert error and "can't be read yet" in text and "ask again in a minute" in text


def test_a_first_sync_that_fails_leaves_nothing_half_made(tmp_path):
    cfg = mirrored(f"file://{tmp_path}/nowhere.git", tmp_path / "mirrors")
    mirror = mirror_of(cfg)
    with pytest.raises(SyncError):
        mirror.sync()
    assert not mirror.ready
    assert not mirror.git_dir.with_suffix(".new").exists()
    assert mirror.status().error and mirror.status().synced is None


# --- keeping it fresh -----------------------------------------------------------------------------------------------


async def test_the_sync_follows_the_host(remote, tmp_path, shop):
    _, ids = shop
    cfg = mirrored(f"file://{remote}", tmp_path / "mirrors")
    mirror = mirror_of(cfg)
    mirror.sync()

    pushed = push(remote, tmp_path / "work", "NOTE = 1\n", "Add notes")
    git(remote, "update-ref", "-d", "refs/heads/feature/discounts")  # a branch deleted on the host
    git(remote, "tag", "v0.3", pushed)
    text, _ = await ask(cfg, "read_file", repo="shop", path="src/shop/notes.py")
    assert "has no file" in text  # not before the sync
    assert mirror.sync() == "2 refs moved, 1 dropped, 1 file' contents fetched"
    text, error = await ask(cfg, "read_file", repo="shop", path="src/shop/notes.py")
    assert not error and "NOTE = 1" in text and pushed[:12] in text
    refs, _ = await ask(cfg, "list_refs", repo="shop")
    assert not re.search(r"^  feature/discounts ", refs, re.M) and "v0.3" in refs

    # A force-push: main rewound to an older commit, and a new history on top of it.
    git(remote, "update-ref", "refs/heads/main", ids["fix"])
    forced = push(remote, tmp_path / "work2", "NOTE = 2\n", "Notes, again", date="2026-03-11T10:00:00+00:00")
    assert mirror.sync().startswith("1 ref moved")
    text, _ = await ask(cfg, "log", repo="shop", max_count=3)
    assert forced[:12] in text and pushed[:12] not in text
    text, error = await ask(cfg, "read_file", repo="shop", path="src/shop/notes.py", ref=pushed)
    assert not error and "NOTE = 1" in text  # the commit it left behind is still readable by its id


async def test_refs_narrow_what_the_mirror_keeps(remote, tmp_path):
    cfg = mirrored(f"file://{remote}", tmp_path / "mirrors", refs=["v*"])
    mirror_of(cfg).sync()
    text, _ = await ask(cfg, "list_refs", repo="shop")
    assert "* main" in text and "v0.1" in text and "v0.2" in text  # the default branch always
    assert not re.search(r"^  feature/discounts ", text, re.M)
    text, error = await ask(cfg, "read_file", repo="shop", path="README.md", ref="feature/discounts")
    assert error and "its mirror keeps the branches and tags" in text


async def test_a_failed_sync_keeps_serving_and_says_why(remote, tmp_path):
    cfg = mirrored(f"file://{remote}", tmp_path / "mirrors")
    mirror = mirror_of(cfg)
    mirror.sync()
    remote.rename(remote.with_name("moved.git"))
    with pytest.raises(SyncError):
        mirror.sync()
    text, _ = await ask(cfg, "list_repos")
    assert "the last sync failed" in text
    text, error = await ask(cfg, "read_file", repo="shop", path="README.md")
    assert not error and "Acme shop" in text


def test_syncs_of_one_mirror_take_turns(remote, tmp_path):
    """Two syncs at once — two threads, two server processes sharing the folder — one makes the mirror, the other finds
    it made."""
    cfg = mirrored(f"file://{remote}", tmp_path / "mirrors")
    outcomes: list[str] = []
    threads = [threading.Thread(target=lambda: outcomes.append(mirror_of(cfg).sync())) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes)[0].startswith("mirrored for the first time") and sorted(outcomes)[1] == "up to date"


# --- contents: only what is served ----------------------------------------------------------------------------------


async def test_nothing_outside_include_exclude_is_ever_fetched(remote, tmp_path, shop):
    """Counted from the mirror itself, after every tool has read it — old commits, diffs of commits that changed
    excluded files, the history and blame of served ones."""
    _, ids = shop
    settings = {"exclude": ["secrets", "**/fixtures/**"]}
    cfg = mirrored(f"file://{remote}", tmp_path / "mirrors", **settings)
    mirror = mirror_of(cfg)
    mirror.sync()
    for tool, arguments in [
        ("list_files", {"recursive": True, "ref": ids["settings"]}),
        ("read_file", {"path": "config/legacy.ini", "ref": ids["settings"]}),
        ("show_commit", {"commit": ids["settings"]}),
        ("show_commit", {"commit": ids["discounts"]}),
        ("diff", {"base": ids["start"], "head": "feature/discounts"}),
        ("log", {}),
        ("blame", {"path": "src/shop/pricing.py", "ref": "feature/discounts"}),
    ]:
        text, error = await ask(cfg, tool, repo="shop", **arguments)
        assert not error, (tool, text)
    text, error = await ask(cfg, "read_file", repo="shop", path="secrets/prod.env", ref=ids["discounts"])
    assert error and "outside what this server serves" in text
    matcher = Matcher(exclude=settings["exclude"])
    every = contents_by_path(remote)
    served = {oid for oid, path in every if matcher.allows(path)}
    held = blobs_in(mirror.git_dir)
    assert held <= served
    assert {oid for oid, path in every if path.startswith("secrets/")}.isdisjoint(held)
    assert git(remote, "rev-parse", f"{ids['settings']}:config/legacy.ini") in held  # fetched when it was read


def test_ensure_never_fetches_a_path_that_is_not_served(remote, tmp_path, shop):
    """Whoever asks — a tool with a bug included — the mirror fetches nothing outside include / exclude."""
    _, ids = shop
    cfg = mirrored(f"file://{remote}", tmp_path / "mirrors", exclude=["secrets"], refs=["main"])
    mirror = mirror_of(cfg)
    mirror.sync()
    secret = git(remote, "rev-parse", f"{ids['discounts']}:secrets/prod.env")
    old_cart = git(remote, "rev-parse", f"{ids['start']}:src/shop/cart.py")
    assert mirror.ensure([(secret, "secrets/prod.env"), (old_cart, "src/shop/cart.py")]) == 1
    held = blobs_in(mirror.git_dir)
    assert old_cart in held and secret not in held


async def test_blame_follows_a_renamed_file_and_says_where_it_must_stop(tmp_path):
    """A file moved whole is followed (git finds it by its contents' id, reading nothing); a file renamed with changes
    can't be, unless the mirror holds the files deleted beside it — blame stops there, and says so."""
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-q", "-b", "main")
    write(source, "old.py", "".join(f"line {i}\n" for i in range(1, 31)))
    write(source, "private/key.txt", "made-up-key\n")
    commit(source, "Write old.py", ADA, "2026-04-01T10:00:00+00:00")
    git(source, "mv", "old.py", "mid.py")
    commit(source, "Move it whole", ADA, "2026-04-02T10:00:00+00:00")
    git(source, "rm", "-q", "mid.py", "private/key.txt")
    write(source, "new.py", "".join(f"line {i}\n" for i in range(1, 31)) + "line 31\n")
    renamed = commit(source, "Rename it with a change", ALAN, "2026-04-03T10:00:00+00:00")
    write(source, "new.py", "".join(f"line {i}\n" for i in range(1, 32)) + "line 32\n")
    commit(source, "Add a line", ADA, "2026-04-04T10:00:00+00:00")
    remote = make_remote(source, tmp_path / "remotes" / "app.git")
    cfg = mirrored(f"file://{remote}", tmp_path / "mirrors", exclude=["private"])
    mirror_of(cfg).sync()

    whole, error = await ask(cfg, "blame", repo="shop", path="mid.py", ref="main~2")
    assert not error and "Write old.py" in whole and "stops" not in whole
    for ref in ("main", "main~1"):  # after the rename, and at it
        text, error = await ask(cfg, "blame", repo="shop", path="new.py", ref=ref)
        assert not error, text
        assert f"Blame stops at {renamed[:12]}" in text and "Rename it with a change" in text
        assert ("Add a line" in text) == (ref == "main")
    key = git(remote, "rev-parse", "main~2:private/key.txt")
    assert key not in blobs_in(mirror_of(cfg).git_dir)


async def test_a_mirror_s_guidance_is_read_from_its_default_branch(tmp_path):
    from repos import AGENTS_MD, build_guided

    build_guided(tmp_path / "guided")
    remote = make_remote(tmp_path / "guided", tmp_path / "remotes" / "guided.git")
    cfg = mirrored(f"file://{remote}", tmp_path / "mirrors", exclude=["secrets"])
    mirror_of(cfg).sync()
    text, error = await ask(cfg, "read_guidance", repo="shop")
    assert not error and AGENTS_MD.strip().split("\n")[-1] in text and "vault password" not in text


# --- the command line -----------------------------------------------------------------------------------------------


def test_sync_brings_every_mirror_up_to_date_once(remote, tmp_path, capsys):
    file = tmp_path / "config.yaml"
    file.write_text(f"repositories:\n  - url: file://{remote}\nmirrors:\n  folder: {tmp_path / 'mirrors'}\n")
    main(["--config", str(file), "--sync"])
    assert "shop: mirrored for the first time" in capsys.readouterr().out
    main(["--config", str(file), "--sync"])
    assert "shop: up to date" in capsys.readouterr().out


def test_check_asks_the_host_and_keeps_nothing(remote, tmp_path, capsys):
    file = tmp_path / "config.yaml"
    file.write_text(
        f"repositories:\n  - url: file://{remote}\n    refs: [main]\nmirrors:\n  folder: {tmp_path / 'mirrors'}\n"
    )
    main(["--config", str(file), "--check"])
    out = capsys.readouterr().out
    assert f"shop  file://{remote}" in out and "not made yet" in out
    assert "host: reachable: 2 branches and 2 tags, of which it keeps 1 and 0" in out
    assert not (tmp_path / "mirrors").exists() or not any((tmp_path / "mirrors").glob("*.git"))


def test_check_says_when_the_host_can_t_be_reached(tmp_path, capsys):
    file = tmp_path / "config.yaml"
    file.write_text(f"repositories:\n  - url: file://{tmp_path}/gone.git\nmirrors:\n  folder: {tmp_path}/m\n")
    main(["--config", str(file), "--check"])
    assert "host: can't be reached:" in capsys.readouterr().out


def test_mirrors_go_to_the_cache_folder_by_default(remote, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    cfg = parse_config({"repositories": [{"url": f"file://{remote}"}]}, tmp_path)
    assert cfg.repositories[0].git_dir.startswith(str(tmp_path / "cache" / "repo-reader-mcp" / "shop-"))
    assert os.path.basename(cfg.mirrors_folder) == "repo-reader-mcp"


async def test_attributes_the_mirror_doesn_t_hold_don_t_stop_a_diff(tmp_path):
    """In a bare repository git reads `.gitattributes` from the commit; when include / exclude keeps it out, the mirror
    never fetched it — a diff and a blame still answer."""
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-q", "-b", "main")
    write(source, ".gitattributes", "*.txt diff=custom\n*.dat binary\n")
    write(source, "notes.txt", "one\ntwo\n")
    commit(source, "First notes", ADA, "2026-04-01T10:00:00+00:00")
    write(source, "notes.txt", "one\nthree\n")
    commit(source, "Change the notes", ADA, "2026-04-02T10:00:00+00:00")
    remote = make_remote(source, tmp_path / "remotes" / "notes.git")
    cfg = mirrored(f"file://{remote}", tmp_path / "mirrors", include=["*.txt"])
    mirror = mirror_of(cfg)
    mirror.sync()
    assert git(remote, "rev-parse", "main:.gitattributes") not in blobs_in(mirror.git_dir)
    for tool, arguments in [("show_commit", {"commit": "main"}), ("blame", {"path": "notes.txt"})]:
        text, error = await ask(cfg, tool, repo="shop", **arguments)
        assert not error, (tool, text)


def history(tmp_path: Path, steps) -> Path:
    """A made-up repository built by `steps(source)`, served as a remote."""
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-q", "-b", "main")
    steps(source)
    return make_remote(source, tmp_path / "remotes" / "app.git")


LINES = "".join(f"line {i}\n" for i in range(1, 31))


async def test_blame_follows_a_rename_with_changes_when_everything_is_served(tmp_path):
    """Where a file was renamed with changes, git compares it with the files deleted beside it: served, the mirror
    fetches them and blame goes on through the rename — answering as the repository itself does."""

    def steps(source):
        write(source, "old.py", LINES)
        write(source, "other.py", "x = 1\n")
        commit(source, "Write old.py", ADA, "2026-04-01T10:00:00+00:00")
        write(source, "old.py", LINES + "line 31\n")
        commit(source, "Add a line to old.py", GRACE, "2026-04-02T10:00:00+00:00")
        git(source, "rm", "-q", "old.py", "other.py")
        write(source, "new.py", LINES + "line 31\nline 32\n")
        commit(source, "Rename it with a change", ALAN, "2026-04-03T10:00:00+00:00")

    remote = history(tmp_path, steps)
    cfg = mirrored(f"file://{remote}", tmp_path / "mirrors")
    mirror_of(cfg).sync()
    expected, _ = await ask(config_for(remote), "blame", repo="shop", path="new.py")
    text, error = await ask(cfg, "blame", repo="shop", path="new.py")
    assert not error and text == expected
    assert "Write old.py" in text and "Add a line to old.py" in text and "stops" not in text


async def test_blame_of_a_file_added_beside_deleted_ones_doesn_t_stop(tmp_path):
    """A file simply added in a commit that deleted others: git compares them, finds no rename — and blame answers in
    full, with no note that it stopped."""

    def steps(source):
        write(source, "gone.py", "y = 2\n")
        commit(source, "Write gone.py", ADA, "2026-04-01T10:00:00+00:00")
        git(source, "rm", "-q", "gone.py")
        write(source, "fresh.py", LINES)
        commit(source, "Replace gone.py with fresh.py", GRACE, "2026-04-02T10:00:00+00:00")
        write(source, "fresh.py", LINES + "line 31\n")
        commit(source, "Grow fresh.py", ALAN, "2026-04-03T10:00:00+00:00")

    remote = history(tmp_path, steps)
    cfg = mirrored(f"file://{remote}", tmp_path / "mirrors")
    mirror_of(cfg).sync()
    expected, _ = await ask(config_for(remote), "blame", repo="shop", path="fresh.py")
    text, error = await ask(cfg, "blame", repo="shop", path="fresh.py")
    assert not error and text == expected and "stops" not in text


async def test_blame_of_a_path_that_was_once_a_submodule(tmp_path):
    def steps(source):
        body = b"tree 4b825dc642cb6eb9a060e54bf8d69288fbee4904\n"
        body += b"author a <a@example.com> 0 +0000\ncommitter a <a@example.com> 0 +0000\n\nx\n"
        commit_id = git(source, "hash-object", "-t", "commit", "--stdin", "-w", data=body)
        git(source, "update-index", "--add", "--cacheinfo", f"160000,{commit_id},lib")
        write(source, "README.md", "hi\n")
        git(source, "add", "README.md")
        git(source, "commit", "-q", "-m", "A submodule at lib", date="2026-04-01T10:00:00+00:00")
        git(source, "rm", "-q", "--cached", "lib")
        write(source, "lib", LINES)
        commit(source, "lib becomes a file", GRACE, "2026-04-02T10:00:00+00:00")

    remote = history(tmp_path, steps)
    cfg = mirrored(f"file://{remote}", tmp_path / "mirrors")
    mirror_of(cfg).sync()
    expected, _ = await ask(config_for(remote), "blame", repo="shop", path="lib")
    text, error = await ask(cfg, "blame", repo="shop", path="lib")
    assert not error and text == expected


async def test_a_mailmap_the_mirror_doesn_t_hold_doesn_t_stop_it(tmp_path):
    """In a bare repository git reads `.mailmap` from the default branch for every history and blame; kept out by
    include, the mirror never fetched it — and nothing stops. Names are shown as each commit wrote them, on a mirror
    as on any repository."""

    def steps(source):
        write(source, ".mailmap", "Ada L. <ada@example.com> Ada Lovelace <ada@example.com>\n")
        write(source, "src/app.py", LINES)
        commit(source, "Start", ADA, "2026-04-01T10:00:00+00:00")

    remote = history(tmp_path, steps)
    for name, settings in (("held-out", {"include": ["src"]}), ("served", {})):
        cfg = mirrored(f"file://{remote}", tmp_path / f"mirrors-{name}", **settings)
        mirror_of(cfg).sync()
        for tool, arguments in [("log", {}), ("blame", {"path": "src/app.py"}), ("read_file", {"path": "src/app.py"})]:
            text, error = await ask(cfg, tool, repo="shop", **arguments)
            assert not error, (name, tool, text)
            local, _ = await ask(config_for(remote, **settings), tool, repo="shop", **arguments)
            assert text == local and "Ada L." not in text, (name, tool)


async def test_a_host_whose_head_is_not_a_branch(remote, tmp_path):
    """A host's HEAD can be a commit rather than a branch: the mirror's default branch is the one at that commit."""
    git(remote, "update-ref", "--no-deref", "HEAD", git(remote, "rev-parse", "main"))
    cfg = mirrored(f"file://{remote}", tmp_path / "mirrors")
    mirror_of(cfg).sync()
    text, error = await ask(cfg, "read_file", repo="shop", path="README.md")
    assert not error and "main @" in text
