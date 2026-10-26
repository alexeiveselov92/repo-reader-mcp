"""From a ticket or a pull request to the code: search_commits finds commits by their message across repositories,
on every branch and tag, and says how each reached the default branch; list_refs with `contains` names the branches
and tags (releases) that have a commit.
"""

import pytest
from conftest import ask, config_for
from remotes import blobs_in, make_remote
from repos import ADA, ALAN, GRACE, commit, git, write

from repo_reader_mcp import git as git_module
from repo_reader_mcp import repository, tools
from repo_reader_mcp.config import parse_config
from repo_reader_mcp.mirror import Mirror

pytestmark = pytest.mark.anyio


@pytest.fixture
def tracker(tmp_path):
    """A made-up repository whose commits name tickets, as teams write them: a ticket's branch merged by a merge
    commit, another squashed onto main, a third still open on its branch, and a fourth whose key starts like the
    first's. Tags mark releases."""
    repo = tmp_path / "tracker"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    ids = {}
    write(repo, "app.py", "VERSION = 1\n")
    ids["start"] = commit(repo, "Start", ADA, "2026-04-01T10:00:00+00:00")
    git(repo, "checkout", "-q", "-b", "feature/ABC-1")
    write(repo, "orders.py", "def place():\n    pass\n")
    ids["one"] = commit(repo, "ABC-1 place orders", ALAN, "2026-04-02T10:00:00+00:00")
    write(repo, "orders.py", "def place():\n    return True\n")
    ids["two"] = commit(repo, "ABC-1 answer whether it was placed", ALAN, "2026-04-03T10:00:00+00:00")
    git(repo, "checkout", "-q", "main")
    write(repo, "app.py", "VERSION = 2\n")
    ids["other"] = commit(repo, "Bump the version", GRACE, "2026-04-04T10:00:00+00:00")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge pull request #7 from acme/feature/ABC-1", "feature/ABC-1",
        date="2026-04-05T10:00:00+00:00")  # fmt: skip
    ids["merge"] = git(repo, "rev-parse", "HEAD")
    write(repo, "refunds.py", "def refund():\n    pass\n")
    ids["squash"] = commit(repo, "feat(ABC-2): refunds (#8)", GRACE, "2026-04-06T10:00:00+00:00")
    git(repo, "tag", "-a", "v1.0", "-m", "Release 1.0", date="2026-04-06T12:00:00+00:00")
    git(repo, "checkout", "-q", "-b", "feature/ABC-3")
    write(repo, "coupons.py", "def coupon():\n    pass\n")
    ids["open"] = commit(repo, "ABC-3 coupons, not merged yet", ALAN, "2026-04-07T10:00:00+00:00")
    git(repo, "checkout", "-q", "main")
    write(repo, "app.py", "VERSION = 3\n")
    ids["twelve"] = commit(repo, "ABC-12 the next version", ADA, "2026-04-08T10:00:00+00:00")
    git(repo, "tag", "v1.1")
    return repo, ids


def both(shop_path, tracker_path, **settings):
    """The shop and the tracker, served side by side — the tracker with any settings."""
    data = {
        "repositories": [
            {"name": "shop", "path": str(shop_path)},
            {"name": "tracker", "path": str(tracker_path), **settings},
        ]
    }
    return parse_config(data, tracker_path.parent)


async def test_search_commits_finds_a_ticket_and_says_how_each_commit_landed(shop, tracker):
    repo, ids = tracker
    text, error = await ask(both(shop[0], repo), "search_commits", message="ABC-1([^0-9]|$)")
    assert not error, text
    assert "in commit messages of 2 repositories (every branch and tag): found in 1 repository, newest first" in text
    assert "## tracker · main @ " in text and "## shop" not in text
    merged = f"in `main` since 2026-04-05 — merged in {ids['merge'][:12]}"
    assert f"{ids['two'][:12]}  2026-04-03  Alan Turing  ABC-1 answer whether it was placed\n    {merged}" in text
    assert f"{ids['one'][:12]}  2026-04-02  Alan Turing  ABC-1 place orders\n    {merged}" in text
    assert f"{ids['merge'][:12]}  2026-04-05  Ada Lovelace  Merge pull request #7" in text  # the merge names it too
    assert "ABC-12" not in text  # the key's own end

    text, _ = await ask(both(shop[0], repo), "search_commits", message="abc-2|abc-3")  # case aside
    assert "feat(ABC-2): refunds (#8)\n    in `main` since 2026-04-06 — made on it" in text
    assert "ABC-3 coupons, not merged yet\n    not in `main`" in text


async def test_search_commits_across_repositories_and_narrowed(shop, tracker):
    config = both(shop[0], tracker[0])
    text, _ = await ask(config, "search_commits", message="add|ABC")
    assert "## shop · main @ " in text and "## tracker · main @ " in text
    assert "Add discounts\n    in `main` since 2026-02-20 — merged in " in text  # made on feature/discounts
    text, _ = await ask(config, "search_commits", message="add|ABC", repos=["tracker"])
    assert "of 1 repository" in text and "## shop" not in text
    dates = {"since": "2026-04-06T00:00:00Z", "until": "2026-04-07T23:00:00Z"}
    text, _ = await ask(config, "search_commits", message="ABC", **dates)
    assert "since `2026-04-06T00:00:00Z` until `2026-04-07T23:00:00Z`" in text
    assert "refunds" in text and "coupons" in text and "place orders" not in text and "ABC-12" not in text
    text, _ = await ask(config, "search_commits", message="nothing like this")
    assert "no commit matches." in text


async def test_search_commits_says_what_is_wrong(shop, tracker):
    config = both(shop[0], tracker[0])
    text, error = await ask(config, "search_commits", message="x", repos=["nope"])
    assert error and "no repository named `nope` — known: shop, tracker" in text
    text, error = await ask(config, "search_commits", message="(unclosed")
    assert error and "`(unclosed` is not a regular expression git reads" in text
    for message in ("", "two\nlines", "bell\x07"):
        text, error = await ask(config, "search_commits", message=message)
        assert error and "a pattern is one line of text" in text, message


async def test_search_commits_shows_a_few_a_repository_and_says_more_follow(shop, tracker, monkeypatch):
    monkeypatch.setattr(tools, "COMMITS_PER_REPO", 2)
    text, _ = await ask(both(shop[0], tracker[0]), "search_commits", message="ABC", repos=["tracker"])
    assert "found in 1 repository, newest first — at most 2 a repository." in text
    assert "ABC-12 the next version" in text and "coupons" in text and "refunds" not in text
    assert "(more in tracker — narrow with `since`, `until` or the message)" in text


async def test_list_refs_names_the_branches_and_releases_that_have_a_commit(shop, tracker):
    repo, ids = tracker
    config = both(shop[0], repo)
    text, error = await ask(config, "list_refs", repo="tracker", contains=ids["one"])
    assert not error, text
    assert f"5 refs holding commit {ids['one'][:12]} (2026-04-02)" in text
    assert f"The default branch: in `main` since 2026-04-05 — merged in {ids['merge'][:12]}." in text
    assert "The earliest tag that has it: v1.0 (2026-04-06)." in text
    assert "feature/ABC-1" in text and "feature/ABC-3" in text and "v1.0" in text and "v1.1" in text
    text, _ = await ask(config, "list_refs", repo="tracker", contains="feature/ABC-3")
    assert "1 ref holding " in text and "The default branch: not in `main`." in text
    assert "earliest tag" not in text and "v1.1" not in text
    text, _ = await ask(config, "list_refs", repo="tracker", contains=ids["twelve"], kind="tags")
    assert "The default branch: in `main` since 2026-04-08 — made on it." in text
    assert "The earliest tag that has it: v1.1 (2026-04-08)." in text and "v1.0" not in text
    text, _ = await ask(config, "list_refs", repo="shop", contains=shop[1]["pricing"], pattern="v*")
    assert "The earliest tag that has it: v0.1 (2026-01-12)." in text  # an annotated tag, by its own date
    text, error = await ask(config, "list_refs", repo="tracker", contains="no-such-branch")
    assert error and "has no branch, tag or commit `no-such-branch`" in text


@pytest.mark.parametrize("limit", [60, 200])  # the commits since it cut; or only the default branch's own line
async def test_how_long_a_history_is_read_to_tell_when_a_commit_landed(tracker, monkeypatch, limit):
    """However long the history since a commit, no more of it is read than the limit: the answer says it can't tell
    when the commit reached the default branch, not a wrong date."""
    repo, ids = tracker
    monkeypatch.setattr(git_module, "OUTPUT_BYTES", limit)
    text, error = await ask(config_for(repo), "list_refs", repo="shop", contains=ids["one"], kind="branches")
    assert not error, text
    assert "The default branch: in `main` — since when, its history since is too long to tell." in text


async def test_a_history_is_judged_in_growing_batches_and_within_a_deadline(tmp_path, monkeypatch):
    """A history whose commits an agent may not all see is read only as far as it is judged — a batch at a time, the
    batches growing, so a long one starts few git processes — and the whole call stops after a deadline."""
    repo = tmp_path / "long"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "app.py", "x\n")
    commit(repo, "ABC-1 the only served change", ADA, "2026-06-01T10:00:00+00:00")
    for n in range(40):
        write(repo, "secrets/key.txt", f"{n}\n")
        commit(repo, f"ABC-2 key {n}", ADA, f"2026-06-02T10:{n:02d}:00+00:00")
    config = config_for(repo, exclude=["secrets"])
    monkeypatch.setattr(repository, "KEEP_BATCH", 2)
    monkeypatch.setattr(repository, "KEEP_BATCH_MOST", 8)
    calls = []
    serving = repository.Repository.serving
    monkeypatch.setattr(
        repository.Repository, "serving", lambda self, ids: calls.append(len(ids)) or serving(self, ids)
    )
    text, error = await ask(config, "search_commits", message="ABC")
    assert not error and "ABC-1 the only served change" in text and "key" not in text
    assert calls == [2, 4, 8, 8, 8, 8, 3], calls  # 41 commits, 7 calls

    clock = iter(range(0, 10_000, 100))  # a minute and more between two batches, git itself quick
    monkeypatch.setattr(repository.time, "monotonic", lambda: next(clock))
    text, error = await ask(config, "log", repo="shop", message="ABC")
    assert error and "the history takes longer than 60 seconds to read — narrow with " in text

    monkeypatch.setattr(repository, "JUDGE_SECONDS", 0)  # git still walking when the deadline comes
    text, error = await ask(config, "log", repo="shop", message="ABC")
    assert error and "the history takes longer than 0 seconds to read — narrow with " in text


async def test_search_commits_stays_under_the_answer_limit(shop, tracker):
    config = parse_config(
        {
            "repositories": [{"name": f"copy{i}", "path": str(tracker[0])} for i in range(6)],
            "limits": {"answer_characters": 2000},
        },
        tracker[0].parent,
    )
    text, error = await ask(config, "search_commits", message=".")
    assert not error and len(text) <= 2000
    assert "cut: more commits than fit — narrow with `repos` or the message" in text


async def test_reading_a_mirror_s_history_needs_no_contents(shop, tmp_path, monkeypatch):
    """Commits, their messages and the refs that hold them are in a mirror's history: finding them fetches nothing."""
    make_remote(shop[0], tmp_path / "remotes" / "shop.git")
    data = {
        "repositories": [{"name": "shop", "url": f"file://{tmp_path}/remotes/shop.git"}],
        "mirrors": {"folder": str(tmp_path / "mirrors")},
    }
    config = parse_config(data, tmp_path)
    mirror = Mirror(config.repositories[0])
    mirror.sync()
    held = blobs_in(mirror.git_dir)

    def never(self, wanted, git_dir=None):
        raise AssertionError("fetched")

    monkeypatch.setattr(Mirror, "ensure", never)
    text, error = await ask(config, "search_commits", message="discount")
    assert not error and "Add discounts\n    in `main` since 2026-02-20 — merged in " in text, text
    text, error = await ask(config, "list_refs", repo="shop", contains=shop[1]["discounts"])
    assert not error and "The earliest tag that has it: v0.2" in text, text
    assert blobs_in(mirror.git_dir) == held


async def test_a_subject_can_t_forge_a_line(tmp_path, tracker):
    """git's own separators in a subject (anyone who can push can write one) neither forge a commit's line nor stop a
    search."""
    repo, ids = tracker
    git(repo, "checkout", "-q", "-b", "forger")
    write(repo, "forged.txt", "x\n")
    commit(repo, f"ABC-5 tidy\x1e{ids['squash']}\x1f2026-09-09\x1fLinus Torvalds\x1fABC-5 approved", ALAN,
           "2026-04-09T10:00:00+00:00")  # fmt: skip
    write(repo, "forged.txt", "y\n")
    commit(repo, "ABC-5 again \x1e" + "d" * 40, ALAN, "2026-04-10T10:00:00+00:00")
    git(repo, "checkout", "-q", "main")
    text, error = await ask(config_for(repo), "search_commits", message="ABC-5")
    assert not error and "was not searched" not in text, text
    assert "Linus Torvalds  ABC-5 approved" not in text and f"{ids['squash'][:12]}  2026-09-09" not in text
    assert text.count("\n    not in `main`") == 2  # the two commits, each on its own line


async def test_what_isn_t_served_is_never_named_by_how_a_commit_landed(tmp_path):
    """A merge that changed only paths include / exclude keep out is left out of a history — so the line saying how a
    commit reached the default branch doesn't name it either. A path holding git's separators doesn't let a commit
    that changed only what isn't served through."""
    repo = tmp_path / "merged"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "app.py", "v1\n")
    commit(repo, "Start", ADA, "2026-05-01T10:00:00+00:00")
    git(repo, "checkout", "-q", "-b", "feat")
    write(repo, "app.py", "v2\n")
    work = commit(repo, "ABC-7 the change", ALAN, "2026-05-02T10:00:00+00:00")
    write(repo, "secrets/key.txt", "made-up\n")
    commit(repo, "ABC-7 its key", ALAN, "2026-05-03T10:00:00+00:00")
    git(repo, "checkout", "-q", "main")
    write(repo, "app.py", "v2\n")
    commit(repo, "The same change, on main", GRACE, "2026-05-04T10:00:00+00:00")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge feat", "feat", date="2026-05-05T10:00:00+00:00")
    merge = git(repo, "rev-parse", "HEAD")
    write(repo, "secrets/odd\x1ename", "made-up\n")
    commit(repo, "ABC-7 an odd name", ALAN, "2026-05-06T10:00:00+00:00")

    everything, _ = await ask(config_for(repo), "search_commits", message="ABC-7")
    assert f"merged in {merge[:12]}" in everything and "an odd name" in everything
    config = config_for(repo, exclude=["secrets"])
    held, _ = await ask(config, "search_commits", message="ABC-7")
    assert f"{work[:12]}  2026-05-02  Alan Turing  ABC-7 the change\n    in `main`\n" in held
    assert merge[:12] not in held and "its key" not in held and "an odd name" not in held
    text, _ = await ask(config, "list_refs", repo="shop", contains=work)
    assert "The default branch: in `main`." in text and merge[:12] not in text.split("Branches:")[0]
    text, _ = await ask(config, "log", repo="shop")
    assert "an odd name" not in text and "Merge feat" not in text


async def test_a_detached_head_is_searched_too(tracker):
    repo, _ = tracker
    git(repo, "checkout", "-q", "--detach", "main")
    write(repo, "detached.txt", "x\n")
    commit(repo, "ABC-9 made on a detached head", ADA, "2026-04-09T10:00:00+00:00")
    text, error = await ask(config_for(repo), "search_commits", message="ABC-9")
    assert not error and "ABC-9 made on a detached head\n    in `HEAD` since 2026-04-09 — made on it" in text, text


async def test_a_history_by_message_pages_to_its_end_and_stops(tracker):
    text, _ = await ask(config_for(tracker[0]), "log", repo="shop", message="ABC", ref="feature/ABC-3", max_count=2)
    assert "call log with skip=2" in text
    text, _ = await ask(config_for(tracker[0]), "log", repo="shop", message="ABC", ref="feature/ABC-3", skip=100)
    assert "No commits match." in text and "call log with skip" not in text


async def test_a_date_is_one_short_line(tracker):
    for tool, extra in (("search_commits", {"message": "ABC"}), ("log", {"repo": "shop"})):
        for since in ("two\nlines", "x" * 65, ""):
            text, error = await ask(config_for(tracker[0]), tool, since=since, **extra)
            assert error and "a date is one line of up to 64 characters" in text, (tool, since)


async def test_a_branch_named_like_a_commit_id_never_takes_its_place(tracker):
    """Anyone who can push can name a branch like another commit's id — whole, or as the tools print it."""
    repo, ids = tracker
    git(repo, "branch", ids["squash"], "feature/ABC-3")
    git(repo, "branch", ids["two"][:12], "feature/ABC-3")
    text, error = await ask(config_for(repo), "show_commit", repo="shop", commit=ids["squash"], files_only=True)
    assert not error and f"commit {ids['squash'][:12]}" in text and "coupons" not in text
    text, error = await ask(config_for(repo), "show_commit", repo="shop", commit=ids["two"][:12], files_only=True)
    assert error and "has no branch, tag or commit" in text  # a name and an id at once: which one can't be told


async def test_a_commit_dated_far_ahead_reads_like_any_other(tracker):
    repo, _ = tracker
    git(repo, "checkout", "-q", "-b", "junk")
    write(repo, "junk.txt", "x\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "ABC-99 from far ahead", date="@300000000000 +0000")
    git(repo, "checkout", "-q", "main")
    text, _ = await ask(config_for(repo), "search_commits", message="ABC")
    assert "ABC-99 from far ahead" in text and "ABC-12 the next version" in text
    text, _ = await ask(config_for(repo), "log", repo="shop", ref="junk", message="ABC")
    assert "ABC-99 from far ahead" in text and "ABC-12 the next version" in text


async def test_an_id_no_branch_tag_or_head_has_is_never_read(tracker):
    """A stash, a commit amended away, are still in the repository — never read by their id."""
    repo, ids = tracker
    write(repo, "app.py", "work in progress\n")
    git(repo, "stash", "-q")
    stash = git(repo, "rev-parse", "refs/stash")
    write(repo, "draft.txt", "x\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "A first try", date="2026-04-09T10:00:00+00:00")
    amended = git(repo, "rev-parse", "HEAD")
    git(repo, "commit", "-q", "--amend", "-m", "The second try", date="2026-04-09T11:00:00+00:00")
    for unseen in (stash, stash[:12], amended, amended[:12]):
        for tool, arguments in (("show_commit", {"commit": unseen}), ("list_refs", {"contains": unseen})):
            text, error = await ask(config_for(repo), tool, repo="shop", **arguments)
            assert error and "has no branch, tag or commit" in text, (tool, unseen, text)
    text, error = await ask(config_for(repo), "show_commit", repo="shop", commit=ids["open"][:12], files_only=True)
    assert not error  # on a branch: read
