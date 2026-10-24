"""The protections (dev/DESIGN.md, "Safety"; docs/reference/safety.md) — each test fails when its protection is
removed: take the protection out, see the test fail, put it back.
"""

from pathlib import Path

import pytest
from conftest import ask, config_for
from repos import git, write

from repo_reader_mcp import git as git_module
from repo_reader_mcp import repository
from repo_reader_mcp.git import GitError, command
from repo_reader_mcp.repository import ReadError, check_ref

pytestmark = pytest.mark.anyio

TRAP_SCRIPT = """#!/bin/sh
touch "{marker}/ran-$(basename "$0")"
cat "$1" 2>/dev/null
"""


@pytest.fixture(scope="module")
def trap(tmp_path_factory) -> tuple[Path, Path]:
    """A repository whose configuration names programs for git to run — an external diff, a diff driver's command,
    a textconv filter, a signature checker — each of which leaves a mark if run; a file on the server's disk for blame
    to read; and colour forced on. Its last commit carries a (made-up) signature, so reading the log would check it."""
    base = tmp_path_factory.mktemp("trap")
    marks = base / "marks"
    marks.mkdir()
    (base / "private.txt").write_text("A-PRIVATE-LINE-OUTSIDE-THE-REPOSITORY\n")  # a file on the server's disk
    for name in ("external-diff", "driver-diff", "textconv", "gpg"):
        script = base / name
        script.write_text(TRAP_SCRIPT.format(marker=marks))
        script.chmod(0o755)
    repo = base / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, ".gitattributes", "*.txt diff=trap\n")
    write(repo, "notes.txt", "one\ntwo\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "First notes", date="2026-04-01T10:00:00+00:00")
    write(repo, "notes.txt", "one\nthree\n")
    git(repo, "commit", "-q", "-am", "Change the notes", date="2026-04-02T10:00:00+00:00")
    body = git(repo, "cat-file", "commit", "HEAD").split("\n")
    at = next(i for i, line in enumerate(body) if line.startswith("committer "))
    signature = ["gpgsig -----BEGIN PGP SIGNATURE-----", " ", " iQEzBAABCAAdFiEEmadeup", " -----END PGP SIGNATURE-----"]
    signed = "\n".join(body[: at + 1] + signature + body[at + 1 :]) + "\n"
    commit = git(repo, "hash-object", "-t", "commit", "-w", "--stdin", data=signed.encode())
    git(repo, "update-ref", "refs/heads/main", commit)
    # Bare, as a mirror is: git then takes `.gitattributes` from the commit itself, so the textconv driver it names
    # is in force (a checkout read through its git directory has no working files for git to take them from).
    git(base, "clone", "-q", "--bare", str(repo), "bare.git")
    repo = base / "bare.git"
    for key, value in {
        "diff.external": str(base / "external-diff"),
        "diff.trap.textconv": str(base / "textconv"),
        "diff.trap.command": str(base / "driver-diff"),
        "blame.ignoreRevsFile": str(base / "private.txt"),
        "gpg.program": str(base / "gpg"),
        "log.showSignature": "true",
        "color.ui": "always",
        "color.diff": "always",
    }.items():
        git(repo, "config", key, value)
    return repo, marks


# --- only reading commands ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("args", [["push"], ["config", "core.editor", "x"], ["checkout", "main"], []])
def test_only_commands_from_the_fixed_set_are_run(args):
    with pytest.raises(GitError):
        command("/nowhere", args)


# --- refs --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("ref", ["-p", "--output=/tmp/x", "main branch", "a\nb", ""])
def test_a_ref_that_could_be_taken_for_an_option_is_refused(ref):
    with pytest.raises(ReadError):
        check_ref(ref)


async def test_only_a_resolved_commit_id_reaches_git(shop, tmp_path, monkeypatch):
    """A branch can be named like an option (anyone who can push can name one `--output=…`, and `git diff` given that
    writes a file). Even with the check above taken away, such a name is resolved to its commit id first, and only
    the id reaches the commands that would act on it."""
    written = tmp_path / "written"
    copy = tmp_path / "copy"
    git(tmp_path, "clone", "-q", str(shop[0]), str(copy))
    git(copy, "update-ref", f"refs/heads/--output={written}", "HEAD~1")
    monkeypatch.setattr(repository, "check_ref", lambda ref: ref)
    cfg = config_for(copy)
    for tool, arguments in [
        ("diff", {"base": f"--output={written}"}),
        ("diff", {"base": "main", "head": f"--output={written}"}),
        ("log", {"ref": f"--output={written}"}),
        ("blame", {"path": "README.md", "ref": f"--output={written}"}),
        ("show_commit", {"commit": f"--output={written}"}),
        ("read_file", {"path": "README.md", "ref": f"--output={written}"}),
        ("list_files", {"ref": f"--output={written}"}),
    ]:
        text, error = await ask(cfg, tool, repo="shop", **arguments)
        assert not error, (tool, text)  # read at the commit the branch points at
    assert not written.exists()


# --- no program a repository names ------------------------------------------------------------------------------


async def test_no_program_a_repository_names_is_ever_run(trap):
    repo, marks = trap
    cfg = config_for(repo)
    answers = []
    for tool, arguments in [
        ("show_commit", {"commit": "main"}),
        ("diff", {"base": "main~1"}),
        ("log", {}),
        ("blame", {"path": "notes.txt"}),
        ("read_file", {"path": "notes.txt"}),
        ("list_repos", {}),
    ]:
        text, error = await ask(cfg, tool, **({"repo": "shop"} if tool != "list_repos" else {}), **arguments)
        assert not error, (tool, text)
        answers.append(text)
    assert list(marks.iterdir()) == []
    assert not any("A-PRIVATE-LINE" in text for text in answers)  # blame never read the file the config names
    assert "-two\n+three" in answers[0]  # the diff of the file itself, not of a filter's output
    assert not any("\x1b[" in text for text in answers)  # no colour codes


# --- no network --------------------------------------------------------------------------------------------------


async def test_a_partial_clone_never_fetches_what_it_lacks(shop, tmp_path):
    source = tmp_path / "source.git"
    git(tmp_path, "clone", "-q", "--bare", str(shop[0]), str(source))
    git(source, "config", "uploadpack.allowFilter", "true")
    git(tmp_path, "clone", "-q", "--filter=blob:none", "--no-local", f"file://{source}", "partial")
    partial = tmp_path / "partial"
    missing = git(partial, "rev-list", "--objects", "--missing=print", "--all")
    old_pricing = git(partial, "rev-parse", "v0.1:src/shop/pricing.py")
    assert f"?{old_pricing}" in missing  # not in the copy

    text, error = await ask(config_for(partial), "read_file", repo="shop", path="src/shop/pricing.py", ref="v0.1")
    assert error and "partial clone" in text and "never downloads" in text
    still = git(partial, "rev-list", "--objects", "--missing=print", "--all")
    assert f"?{old_pricing}" in still  # and still not


# --- the environment ---------------------------------------------------------------------------------------------


async def test_the_server_s_environment_cannot_redirect_git(shop, monkeypatch):
    monkeypatch.setenv("GIT_NAMESPACE", "elsewhere")
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", "/nowhere")
    text, error = await ask(config_for(shop[0]), "list_refs", repo="shop")
    assert not error and "* main" in text


def test_the_operator_s_choice_of_configuration_files_is_kept(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/etc/acme-gitconfig")
    monkeypatch.setenv("GIT_DIR", "/elsewhere")
    env = git_module.environment()
    assert env["GIT_CONFIG_GLOBAL"] == "/etc/acme-gitconfig" and "GIT_DIR" not in env


# --- sizes -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "arguments", "note"),
    [
        ("list_files", {"recursive": True}, "holds more than the server reads at once"),
        ("list_files", {}, "holds more than the server reads at once"),
        ("list_refs", {}, "more refs than are read at once"),
        ("log", {}, "more commits: call log with skip="),
        ("show_commit", {"commit": "main"}, "more files changed than the server reads at once"),
        ("diff", {"base": "v0.1"}, "more files changed than the server reads at once"),
        ("blame", {"path": "src/shop/cart.py"}, "call blame with start_line="),
    ],
)
async def test_git_s_output_is_read_only_up_to_a_limit(shop, monkeypatch, tool, arguments, note):
    """However large a tree, a history or a diff, no more of git's output than the limit is read; the answer says it
    is partial."""
    monkeypatch.setattr(git_module, "OUTPUT_BYTES", 300)
    text, error = await ask(config_for(shop[0]), tool, repo="shop", **arguments)
    assert not error, text
    assert note in text


# --- include / exclude -------------------------------------------------------------------------------------------

SECRETS = ("made-up-secret-value", "made-up-discount-key", "DISCOUNT_KEY", "carts.json")


async def test_excluded_paths_never_appear_in_any_answer(shop):
    path, ids = shop
    cfg = config_for(path, exclude=["secrets", "**/fixtures/**"])
    seen = []
    for tool, arguments in [
        ("list_files", {"recursive": True}),
        ("list_files", {}),
        ("show_commit", {"commit": ids["discounts"]}),
        ("show_commit", {"commit": ids["settings"]}),
        ("diff", {"base": "v0.1", "head": "feature/discounts"}),
    ]:
        text, error = await ask(cfg, tool, repo="shop", **arguments)
        assert not error, (tool, text)
        seen.append(text)
        assert not any(secret in text for secret in SECRETS), (tool, text)
    assert "secrets/" not in seen[0] and "secrets/" not in seen[1]
    assert "1 file outside what this server serves not shown" in seen[2]

    for tool, arguments in [
        ("read_file", {"path": "secrets/prod.env"}),
        ("blame", {"path": "secrets/prod.env"}),
        ("log", {"path": "secrets"}),
        ("log", {"path": "secrets/prod.env"}),
        ("read_file", {"path": "data/fixtures/carts.json"}),
        ("diff", {"base": "v0.1", "head": "feature/discounts", "path": "secrets/prod.env"}),
        ("diff", {"base": "v0.1", "path": "secrets"}),
        ("show_commit", {"commit": ids["discounts"], "path": "secrets"}),
    ]:
        text, error = await ask(cfg, tool, repo="shop", **arguments)
        assert error and "outside what this server serves" in text, (tool, text)
    # An excluded folder answers as a folder that isn't there: its existence is not told.
    hidden, _ = await ask(cfg, "list_files", repo="shop", path="secrets")
    absent, _ = await ask(cfg, "list_files", repo="shop", path="nowhere")
    assert hidden.replace("secrets/", "X/") == absent.replace("nowhere/", "X/")


async def test_the_history_leaves_out_commits_that_changed_only_what_is_not_served(shop, tmp_path):
    copy = tmp_path / "copy"
    git(tmp_path, "clone", "-q", str(shop[0]), str(copy))
    write(copy, "secrets/prod.env", "API_KEY=made-up-rotated-value\n")
    git(copy, "commit", "-q", "-am", "Rotate secrets/prod.env", date="2026-03-05T10:00:00+00:00")
    git(copy, "commit", "-q", "--allow-empty", "-m", "Release notes only", date="2026-03-06T10:00:00+00:00")

    everything, _ = await ask(config_for(copy), "log", repo="shop")
    assert "Rotate secrets/prod.env" in everything
    held, _ = await ask(config_for(copy, exclude=["secrets"]), "log", repo="shop")
    assert "Rotate secrets" not in held and "(Only commits that changed what this server serves.)" in held
    assert "Release notes only" in held  # it changed nothing, so it tells nothing
    assert "Add discounts" in held  # it changed a served file too
    paged, _ = await ask(config_for(copy, exclude=["secrets"]), "log", repo="shop", max_count=1, skip=1)
    assert "Add the catalog" in paged and "call log with skip=2" in paged  # `skip` counts what the agent sees


async def test_include_takes_only_what_it_names(shop):
    cfg = config_for(shop[0], include=["src/**"])
    text, _ = await ask(cfg, "list_files", repo="shop")
    assert text.split("\n\n", 1)[1].split() == ["src/"]
    text, error = await ask(cfg, "read_file", repo="shop", path="README.md")
    assert error and "outside what this server serves" in text
