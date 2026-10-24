"""Every reading tool over the made-up shop, through the SDK's own client — what any MCP client sees."""

import pytest
from conftest import ask, config_for

from repo_reader_mcp.config import Config

pytestmark = pytest.mark.anyio


@pytest.fixture
def cfg(shop):
    return config_for(shop[0], description="A made-up shop.")


@pytest.fixture
def ids(shop):
    return shop[1]


# --- list_repos --------------------------------------------------------------------------------------------------


async def test_list_repos_names_each_repository_and_where_its_default_branch_is(cfg, ids):
    text, error = await ask(cfg, "list_repos")
    assert not error
    assert "## shop" in text and "A made-up shop." in text
    assert f"Default branch: main @ {ids['catalog'][:12]} (2026-03-01) — Add the catalog" in text
    assert "2 branches, 2 tags" in text


async def test_list_repos_without_repositories_says_so():
    text, error = await ask(Config(), "list_repos")
    assert not error and "No repositories are configured" in text


# --- list_refs ---------------------------------------------------------------------------------------------------


async def test_list_refs_lists_branches_and_tags_with_their_commits(cfg, ids):
    text, _ = await ask(cfg, "list_refs", repo="shop")
    assert f"* main               {ids['catalog'][:12]}" in text
    assert f"  feature/discounts  {ids['discounts'][:12]}" in text
    assert f"v0.1               {ids['pricing'][:12]}" in text  # an annotated tag: the commit it points at
    assert f"v0.2               {ids['merge'][:12]}" in text


async def test_list_refs_narrows_by_kind_and_pattern(cfg):
    text, _ = await ask(cfg, "list_refs", repo="shop", kind="tags", pattern="v0.1*")
    assert "v0.1" in text and "v0.2" not in text and "main" not in text
    text, _ = await ask(cfg, "list_refs", repo="shop", kind="branches")
    assert "feature/discounts" in text and "Tags:" not in text


async def test_an_unknown_repository_names_the_known_ones(cfg):
    text, error = await ask(cfg, "list_refs", repo="nope")
    assert error and "no repository named `nope` — known: shop" in text


# --- read_file ---------------------------------------------------------------------------------------------------


async def test_read_file_reads_any_ref(cfg, ids):
    old, _ = await ask(cfg, "read_file", repo="shop", path="src/shop/cart.py", ref="v0.1")
    new, _ = await ask(cfg, "read_file", repo="shop", path="src/shop/cart.py")
    assert old.startswith(f"shop · src/shop/cart.py · v0.1 @ {ids['pricing'][:12]} (2026-01-12) · lines 1–12 of 12")
    assert "if not self.items" not in old
    assert "12\t        if not self.items:" in new
    by_id, _ = await ask(cfg, "read_file", repo="shop", path="src/shop/cart.py", ref=ids["start"][:7])
    assert f"commit {ids['start'][:12]} (2026-01-05)" in by_id
    relative, _ = await ask(cfg, "read_file", repo="shop", path="src/shop/pricing.py", ref="feature/discounts~1")
    assert "discounted" not in relative


async def test_read_file_never_shows_what_is_not_committed(cfg):
    text, _ = await ask(cfg, "read_file", repo="shop", path="README.md")
    assert "UNCOMMITTED" not in text and "A made-up shop for tests." in text
    text, error = await ask(cfg, "read_file", repo="shop", path="src/shop/draft.py")
    assert error and "has no file `src/shop/draft.py`" in text


async def test_read_file_reads_a_deleted_file_at_a_commit_that_had_it(cfg, ids):
    text, error = await ask(cfg, "read_file", repo="shop", path="config/legacy.ini")
    assert error
    text, error = await ask(cfg, "read_file", repo="shop", path="config/legacy.ini", ref=ids["settings"])
    assert not error and "mode = classic" in text


async def test_read_file_answers_a_window_and_says_how_to_go_on(cfg):
    text, _ = await ask(cfg, "read_file", repo="shop", path="data/products.csv")
    assert len(text) <= 40_000
    assert "call read_file with start_line=" in text
    text, _ = await ask(cfg, "read_file", repo="shop", path="data/products.csv", start_line=100, max_lines=3)
    assert "lines 100–102 of 3001" in text
    assert text.count("\n") < 10 and "102\t101,product-101,201" in text
    text, error = await ask(cfg, "read_file", repo="shop", path="data/products.csv", start_line=5000)
    assert error and "has 3001 lines" in text


async def test_read_file_cuts_a_very_long_line(cfg):
    text, _ = await ask(cfg, "read_file", repo="shop", path="static/app.min.js")
    assert "more characters]" in text and len(text) < 3000


async def test_read_file_describes_what_it_does_not_show(cfg):
    text, _ = await ask(cfg, "read_file", repo="shop", path="assets/logo.png")
    assert "A binary file of 272 bytes" in text
    text, _ = await ask(cfg, "read_file", repo="shop", path="docs/latest.md")
    assert "A symbolic link to `../README.md` — not followed" in text
    text, error = await ask(cfg, "read_file", repo="shop", path="src/shop")
    assert error and "is a folder" in text


async def test_read_file_names_what_is_wrong_with_a_ref_or_a_path(cfg):
    text, error = await ask(cfg, "read_file", repo="shop", path="README.md", ref="no-such-branch")
    assert error and "no branch, tag or commit `no-such-branch`" in text and "list_refs" in text
    text, error = await ask(cfg, "read_file", repo="shop", path="../outside")
    assert error and "not a plain path" in text


# --- list_files --------------------------------------------------------------------------------------------------


async def test_list_files_shows_folders_then_files(cfg):
    text, _ = await ask(cfg, "list_files", repo="shop")
    assert "8 folders, 1 file" in text
    body = text.split("\n\n", 1)[1].split()
    assert body == ["assets/", "config/", "data/", "docs/", "secrets/", "src/", "static/", "tests/", "README.md"]


async def test_list_files_lists_a_folder_or_everything_under_it(cfg):
    text, _ = await ask(cfg, "list_files", repo="shop", path="src/shop")
    assert "src/shop/cart.py" in text and "src/shop/draft.py" not in text
    text, _ = await ask(cfg, "list_files", repo="shop", recursive=True)
    assert "src/shop/cart.py" in text and "docs/latest.md (link)" in text
    assert "src/shop/draft.py" not in text


async def test_list_files_at_an_old_ref(cfg):
    text, _ = await ask(cfg, "list_files", repo="shop", ref="v0.1", recursive=True)
    assert "src/shop/pricing.py" in text and "config/" not in text


async def test_list_files_says_when_a_path_is_a_file_or_nothing(cfg):
    text, error = await ask(cfg, "list_files", repo="shop", path="README.md")
    assert error and "is a file" in text
    text, error = await ask(cfg, "list_files", repo="shop", path="nowhere")
    assert error and "no files this server serves under nowhere/" in text


# --- log ---------------------------------------------------------------------------------------------------------


async def test_log_is_newest_first(cfg, ids):
    text, _ = await ask(cfg, "log", repo="shop")
    lines = [line for line in text.splitlines() if line[:12] in {i[:12] for i in ids.values()}]
    order = ("catalog", "merge", "fix", "discounts", "settings", "pricing", "start")
    assert [line[:12] for line in lines] == [ids[k][:12] for k in order]
    assert f"{ids['fix'][:12]}  2026-02-15  Grace Hopper  Fix the cart total for empty carts" in text


async def test_log_of_a_path_an_author_a_message_and_dates(cfg, ids):
    text, _ = await ask(cfg, "log", repo="shop", path="src/shop/pricing.py")
    assert ids["discounts"][:12] in text and ids["pricing"][:12] in text and ids["fix"][:12] not in text
    text, _ = await ask(cfg, "log", repo="shop", author="grace")
    assert text.count("Grace Hopper") == 2
    text, _ = await ask(cfg, "log", repo="shop", message="CART")
    assert ids["fix"][:12] in text and ids["start"][:12] in text and ids["pricing"][:12] not in text
    text, _ = await ask(cfg, "log", repo="shop", since="2026-02-01", until="2026-02-16")
    body = text.split("\n\n", 1)[1]  # the header names the commit main is at
    found = {k for k, v in ids.items() if v[:12] in body}
    assert found == {"settings", "discounts", "fix"}


async def test_log_pages_on(cfg, ids):
    text, _ = await ask(cfg, "log", repo="shop", max_count=2)
    assert "call log with skip=2" in text
    text, _ = await ask(cfg, "log", repo="shop", max_count=2, skip=2)
    assert ids["fix"][:12] in text and ids["discounts"][:12] in text and ids["merge"][:12] not in text


async def test_log_of_another_branch(cfg, ids):
    text, _ = await ask(cfg, "log", repo="shop", ref="feature/discounts")
    assert ids["discounts"][:12] in text and ids["fix"][:12] not in text


# --- show_commit -------------------------------------------------------------------------------------------------


async def test_show_commit_gives_the_message_the_files_and_the_diff(cfg, ids):
    text, _ = await ask(cfg, "show_commit", repo="shop", commit=ids["fix"])
    assert text.startswith(f"shop · commit {ids['fix'][:12]}\nAuthor: Grace Hopper, 2026-02-15T10:00:00+00:00")
    assert "    Fix the cart total for empty carts" in text
    assert "M  src/shop/cart.py  +2" in text
    assert "+        if not self.items:" in text


async def test_show_commit_of_a_merge_and_of_the_first_commit(cfg, ids):
    text, _ = await ask(cfg, "show_commit", repo="shop", commit=ids["merge"])
    assert "a merge; the changes below are against the first parent" in text and "+def discounted" in text
    text, _ = await ask(cfg, "show_commit", repo="shop", commit=ids["start"])
    assert "Parents: none" in text and "A  src/shop/cart.py  +12" in text and "A  README.md  +3" in text


async def test_show_commit_files_only_and_a_path(cfg, ids):
    text, _ = await ask(cfg, "show_commit", repo="shop", commit=ids["settings"], files_only=True)
    assert "A  config/settings.yml  +2" in text and "diff --git" not in text
    text, _ = await ask(cfg, "show_commit", repo="shop", commit=ids["settings"], path="config")
    assert "2 files changed under config" in text and "+currency: EUR" in text and "fixtures" not in text


# --- diff --------------------------------------------------------------------------------------------------------


async def test_diff_between_two_tags(cfg, ids):
    text, _ = await ask(cfg, "diff", repo="shop", base="v0.1", head="v0.2")
    assert text.startswith(f"shop · diff v0.1 @ {ids['pricing'][:12]} (2026-01-12) → v0.2 @ {ids['merge'][:12]}")
    for path in ("src/shop/cart.py", "src/shop/pricing.py", "config/settings.yml"):
        assert f"  {path}  " in text
    assert "+def discounted" in text


async def test_diff_since_fork_shows_only_what_the_branch_changed(cfg, ids):
    text, _ = await ask(cfg, "diff", repo="shop", base="v0.1", head="feature/discounts", since_fork=True)
    assert f"from their merge base {ids['pricing'][:12]}" in text
    assert "src/shop/pricing.py" in text
    text, _ = await ask(cfg, "diff", repo="shop", base="main", head="feature/discounts", since_fork=True)
    assert "No changes." in text  # already merged


async def test_diff_head_defaults_to_the_default_branch_and_a_path_narrows_it(cfg):
    text, _ = await ask(cfg, "diff", repo="shop", base="v0.2", path="config")
    assert "→ main @" in text and "D  config/legacy.ini" in text and "products.csv" not in text


# --- blame -------------------------------------------------------------------------------------------------------


async def test_blame_groups_lines_under_the_commit_that_wrote_them(cfg, ids):
    text, _ = await ask(cfg, "blame", repo="shop", path="src/shop/cart.py")
    assert f"{ids['fix'][:12]} 2026-02-15 Grace Hopper — Fix the cart total for empty carts\n12\t" in text
    assert f"{ids['start'][:12]} 2026-01-05 Ada Lovelace — Start the shop: a cart\n 1\t" in text
    text, _ = await ask(cfg, "blame", repo="shop", path="src/shop/cart.py", start_line=12, max_lines=2)
    assert "lines 12–13 of 14" in text and "Ada Lovelace" not in text


async def test_blame_at_an_old_ref(cfg, ids):
    text, _ = await ask(cfg, "blame", repo="shop", path="src/shop/cart.py", ref="v0.1")
    assert ids["fix"][:12] not in text and "lines 1–12 of 12" in text


# --- answers are capped -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "arguments", "note"),
    [
        ("read_file", {"path": "data/products.csv"}, "call read_file with start_line="),
        ("blame", {"path": "data/products.csv"}, "call blame with start_line="),
        ("list_files", {"recursive": True}, None),
        ("show_commit", {"commit": "main"}, "cut: the diff is longer than the answer"),
        ("diff", {"base": "v0.1"}, "cut: the diff is longer than the answer"),
        ("log", {}, None),
        ("list_refs", {}, None),
    ],
)
async def test_every_answer_stays_under_the_limit(shop, tool, arguments, note):
    cfg = config_for(shop[0], limits={"answer_characters": 2000})
    text, error = await ask(cfg, tool, repo="shop", **arguments)
    assert not error
    assert len(text) <= 2000
    if note:
        assert note in text


def test_dates_read_the_same_whatever_git_s_version_writes():
    from repo_reader_mcp.repository import _iso

    assert _iso("2026-02-15T10:00:00Z") == _iso("2026-02-15T10:00:00+00:00") == "2026-02-15T10:00:00+00:00"
    assert _iso("2026-02-15T12:00:00+02:00") == "2026-02-15T12:00:00+02:00"
