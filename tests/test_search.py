"""search across repositories and grep in one: matching lines with their files and line numbers — and never a path
include / exclude keep out, which git is not even given.
"""

import pytest
from conftest import ask
from remotes import blobs_in, contents_by_path, make_remote
from repos import ALAN, commit, git, write

from repo_reader_mcp.config import parse_config

pytestmark = pytest.mark.anyio


def two(shop_path, **settings):
    """The shop served twice, as `shop` and `copy` — `copy` with any settings."""
    data = {
        "repositories": [{"name": "shop", "path": str(shop_path)}, {"name": "copy", "path": str(shop_path), **settings}]
    }
    return parse_config(data, shop_path.parent)


async def test_search_finds_text_across_repositories(shop):
    text, error = await ask(two(shop[0]), "search", pattern="currency")
    assert not error, text
    assert "`currency` in 2 repositories (their default branches): 2 lines in 2 files of 2 repositories" in text
    assert "## shop · main @ " in text and "## copy · main @ " in text
    assert "config/settings.yml\n  1: currency: EUR" in text


async def test_search_never_looks_where_exclude_keeps_out(shop):
    config = two(shop[0], exclude=["config"])
    text, _ = await ask(config, "search", pattern="currency: EUR")
    assert "## shop" in text and "## copy" not in text  # found in the repository serving it, not in the other
    text, _ = await ask(config, "search", pattern="currency: EUR", repos=["copy"])
    assert "no line matches" in text and "config/settings.yml" not in text


async def test_search_narrows_by_repository_path_and_case(shop):
    config = two(shop[0])
    text, _ = await ask(config, "search", pattern="CURRENCY", repos=["copy"], ignore_case=True)
    assert "in 1 repository" in text and "## copy" in text and "## shop" not in text
    text, _ = await ask(config, "search", pattern="currency", path="src")
    assert "no line matches" in text
    text, error = await ask(config, "search", pattern="x", repos=["nope"])
    assert error and "no repository named `nope`" in text


async def test_search_and_grep_take_a_regular_expression(shop):
    config = two(shop[0])
    text, _ = await ask(config, "search", pattern="locale: [a-z]+$", regex=True, repos=["shop"])
    assert "config/settings.yml\n  2: locale: en" in text
    text, error = await ask(config, "grep", repo="shop", pattern="(unclosed", regex=True)
    assert error and "is not a regular expression git reads" in text
    text, _ = await ask(config, "grep", repo="shop", pattern="(unclosed")  # fixed text by default: nothing to parse
    assert "no line matches" in text


async def test_grep_shows_lines_around_a_match_at_any_ref(shop):
    path, ids = shop
    config = two(path)
    text, error = await ask(config, "grep", repo="shop", pattern="mode = classic", ref="v0.2", context=1)
    assert not error, text
    assert "shop · grep `mode = classic` · v0.2 @ " in text and "1 matching line in 1 file" in text
    assert "config/legacy.ini\n  1- [old]\n  2: mode = classic" in text
    text, _ = await ask(config, "grep", repo="shop", pattern="def discounted", ref=ids["discounts"], files_only=True)
    assert "1 file match" in text and "src/shop/pricing.py" in text


async def test_grep_refuses_a_path_kept_out_and_odd_patterns(shop):
    config = two(shop[0], exclude=["secrets"])
    text, error = await ask(config, "grep", repo="copy", pattern="API", path="secrets")
    assert error and "outside what this server serves" in text
    for pattern in ("", "two\nlines", "bell\x07"):
        text, error = await ask(config, "grep", repo="copy", pattern=pattern)
        assert error and "a pattern is one line of text" in text, pattern


async def test_a_pattern_that_looks_like_an_option_is_just_text(tmp_path):
    repo = tmp_path / "flags"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "notes.txt", "run it with --color=always to see\n--open-files-in-pager=touch is a flag too\n")
    commit(repo, "notes", ALAN, "2026-03-01T10:00:00+00:00")
    config = parse_config({"repositories": [{"name": "flags", "path": str(repo)}]}, tmp_path)
    for pattern in ("--color=always", "--open-files-in-pager=touch"):
        text, error = await ask(config, "grep", repo="flags", pattern=pattern)
        assert not error and "notes.txt" in text and pattern in text, (pattern, text)


async def test_search_on_a_mirror_reads_only_what_it_holds(shop, tmp_path):
    """Excluded contents are not in a mirror: search must not need them — and grep at an older commit fetches the
    served files' contents only."""
    from repo_reader_mcp.mirror import Mirror

    remote = make_remote(shop[0], tmp_path / "remotes" / "shop.git")
    data = {
        "repositories": [{"name": "shop", "url": f"file://{remote}", "exclude": ["secrets", "data"]}],
        "mirrors": {"folder": str(tmp_path / "mirrors")},
    }
    config = parse_config(data, tmp_path)
    mirror = Mirror(config.repositories[0])
    mirror.sync()
    text, error = await ask(config, "search", pattern="EUR")
    assert not error and "config/settings.yml" in text
    text, error = await ask(config, "grep", repo="shop", pattern="def ", ref="v0.1")
    assert not error and "src/shop/" in text
    excluded = {oid for oid, path in contents_by_path(remote) if path.startswith(("secrets/", "data/"))}
    assert not excluded & blobs_in(mirror.git_dir)


async def test_unusual_file_names_are_found(tmp_path):
    repo = tmp_path / "odd"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, 'odd dir/quote"name.txt', "needle here\n")
    write(repo, "plain.txt", "no\n")
    commit(repo, "odd names", ALAN, "2026-03-01T10:00:00+00:00")
    config = parse_config({"repositories": [{"name": "odd", "path": str(repo)}]}, tmp_path)
    text, error = await ask(config, "grep", repo="odd", pattern="needle")
    assert not error and 'odd dir/quote"name.txt\n  1: needle here' in text
