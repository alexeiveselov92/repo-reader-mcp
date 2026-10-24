"""The protections (dev/DESIGN.md, "Safety"; docs/reference/safety.md) — each test fails when its protection is
removed: take the protection out, see the test fail, put it back.
"""

import subprocess
from pathlib import Path

import pytest
from conftest import ask, config_for
from remotes import GitHTTP, blobs_in, make_remote
from repos import git, write

from repo_reader_mcp import git as git_module
from repo_reader_mcp import mirror as mirror_module
from repo_reader_mcp import repository
from repo_reader_mcp.config import parse_config
from repo_reader_mcp.git import GitError, command
from repo_reader_mcp.mirror import Mirror, SyncError
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
    with pytest.raises(GitError, match="is not a command this server runs"):
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


# --- remote repositories: what reaches a host, and how -----------------------------------------------------------

TOKEN = "made-up-token-4f9a2c"


@pytest.fixture
def served(shop, tmp_path) -> Path:
    """A folder of made-up remote repositories, to be served over HTTP on 127.0.0.1."""
    make_remote(shop[0], tmp_path / "remotes" / "shop.git")
    return tmp_path / "remotes"


def remote_config(url: str, folder: Path, **settings):
    data = {"repositories": [{"name": "shop", "url": url, **settings}], "mirrors": {"folder": str(folder)}}
    return parse_config(data, folder.parent)


@pytest.mark.parametrize("args", [["fetch", "origin"], ["ls-remote", "origin"], ["clone", "x"], ["config", "a", "b"]])
def test_a_reading_command_can_t_reach_a_host(args):
    with pytest.raises(GitError, match="is not a command this server runs"):
        command("/nowhere", args)
    line = command("/nowhere", ["log"])
    assert "protocol.allow=never" in line and not any(part.endswith(".allow=always") for part in line)


@pytest.mark.parametrize("args", [["push", "origin"], ["gc"], ["checkout", "main"], ["clone", "x"], ["remote", "add"]])
def test_the_sync_runs_only_its_own_commands(args):
    with pytest.raises(GitError, match="is not a command this server runs"):  # refused before git starts
        git_module.maintain("/nowhere", args)


async def test_reading_a_mirror_never_fetches(served, tmp_path, monkeypatch, shop):
    """With the deliberate fetch taken away, a mirror's missing contents stay missing: the reading commands themselves
    reach no host."""
    cfg = remote_config(f"file://{served}/shop.git", tmp_path / "mirrors", refs=["main"])
    mirror = Mirror(cfg.repositories[0])
    mirror.sync()
    old_cart = git(served / "shop.git", "rev-parse", f"{shop[1]['start']}:src/shop/cart.py")
    assert old_cart not in blobs_in(mirror.git_dir)
    monkeypatch.setattr(Mirror, "ensure", lambda self, wanted, git_dir=None: 0)
    text, error = await ask(cfg, "read_file", repo="shop", path="src/shop/cart.py", ref=shop[1]["start"])
    assert error and "reading never fetches them" in text
    assert old_cart not in blobs_in(mirror.git_dir)


async def test_a_token_travels_in_git_s_environment_only(served, tmp_path, monkeypatch, shop):
    """The token reaches the host — and appears on no command line (which any user of the machine can read), in no
    file of the mirror, in no answer."""
    monkeypatch.setenv("ACME_TOKEN", TOKEN)
    lines: list[str] = []
    real = subprocess.Popen

    def recording(args, *rest, **kwargs):
        lines.extend(str(arg) for arg in args)
        return real(args, *rest, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", recording)
    with GitHTTP(served, token=TOKEN) as host:
        cfg = remote_config(host.url("shop.git"), tmp_path / "mirrors", token_env="ACME_TOKEN", refs=["main"])
        Mirror(cfg.repositories[0]).sync()
        old, error = await ask(cfg, "read_file", repo="shop", path="src/shop/cart.py", ref=shop[1]["start"])
        listing, _ = await ask(cfg, "list_repos")
        assert host.seen and set(host.seen) == {host.expected}
    assert not error and "class Cart" in old  # fetched on purpose, with the token
    basic = host.expected.removeprefix("Basic ")
    assert lines and not any(TOKEN in line or basic in line for line in lines)
    for file in (tmp_path / "mirrors").rglob("*"):
        if file.is_file():
            data = file.read_bytes()
            assert TOKEN.encode() not in data and basic.encode() not in data, file
    assert TOKEN not in listing and basic not in listing


async def test_the_token_goes_to_the_repository_s_host_only(served, tmp_path, monkeypatch):
    """A host that sends git elsewhere (a redirect to another host) doesn't get the token sent along — not even when the
    machine's git configuration says to follow that host's redirects."""
    monkeypatch.setenv("ACME_TOKEN", TOKEN)
    with GitHTTP(served) as elsewhere, GitHTTP(served, token=TOKEN) as host:
        host.redirect_to = elsewhere.base
        gitconfig = tmp_path / "gitconfig"  # the machine's configuration asks to follow redirects from that host
        gitconfig.write_text(f'[http "{host.base}/"]\n\tfollowRedirects = true\n')
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
        cfg = remote_config(host.url("shop.git"), tmp_path / "mirrors", token_env="ACME_TOKEN", refs=["main"])
        with pytest.raises(SyncError) as failed:
            Mirror(cfg.repositories[0]).sync()
        assert host.seen  # the token went to its host
        assert elsewhere.seen == []
    assert "give `url` as the address it redirects to" in str(failed.value)


def test_a_wrong_token_is_answered_by_no_other_credentials(served, tmp_path, monkeypatch):
    """With a token configured, the credential helpers of the server's account are switched off — a refused token is
    never followed by credentials stored for someone else, nor stored by a helper — and so are programs asking for a
    password, which would run with the token in their environment."""
    marker = tmp_path / "helper-ran"
    asked = tmp_path / "askpass-ran"
    askpass = tmp_path / "askpass"
    askpass.write_text(f"#!/bin/sh\nenv > {asked}\necho made-up-password\n")
    askpass.chmod(0o755)
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text(f'[credential]\n\thelper = "!f() {{ touch {marker}; }}; f"\n[core]\n\taskPass = {askpass}\n')
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("SSH_ASKPASS", str(askpass))
    monkeypatch.setenv("ACME_TOKEN", "made-up-wrong-token")
    with GitHTTP(served, token=TOKEN) as host:
        cfg = remote_config(host.url("shop.git"), tmp_path / "mirrors", token_env="ACME_TOKEN")
        with pytest.raises(SyncError) as failed:
            Mirror(cfg.repositories[0]).sync()
    assert "made-up-wrong-token" not in str(failed.value)
    assert not marker.exists()
    assert not asked.exists()  # a program asking for a password would have run with the token in its environment


def test_an_error_never_carries_the_token(served, tmp_path, monkeypatch):
    """Whatever git says, the token is taken out of it — in the error, and in the status every process reads."""
    monkeypatch.setenv("ACME_TOKEN", TOKEN)
    cfg = remote_config("https://example.com/acme/shop.git", tmp_path / "mirrors", token_env="ACME_TOKEN")
    mirror = Mirror(cfg.repositories[0])
    header = next(v for v in mirror.access().env.values() if v.startswith("Authorization: Basic "))
    basic = header.removeprefix("Authorization: Basic ")

    def leaky(git_dir, args, **kwargs):
        raise GitError(f"fatal: header was Authorization: Basic {basic}; token {TOKEN}")

    monkeypatch.setattr(mirror_module, "maintain", leaky)
    with pytest.raises(SyncError) as failed:
        mirror.sync()
    assert TOKEN not in str(failed.value) and basic not in str(failed.value)
    status = mirror.status_file.read_text()
    assert TOKEN not in status and basic not in status and "***" in status


def test_the_sync_reaches_a_host_only_by_its_url_s_protocol(served, tmp_path, monkeypatch):
    """A URL rewritten on the way (`insteadOf` in the machine's configuration, a host's redirect) can't switch git to
    another protocol — not even one the machine's configuration allows: only the configured URL's is."""
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text(
        f'[url "file://{served}/"]\n\tinsteadOf = http://127.0.0.1:9/\n[protocol "file"]\n\tallow = always\n'
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    cfg = remote_config("http://127.0.0.1:9/shop.git", tmp_path / "mirrors")
    mirror = Mirror(cfg.repositories[0])
    with pytest.raises(SyncError) as failed:
        mirror.sync()
    assert "transport 'file' not allowed" in str(failed.value)
    assert not mirror.ready


async def test_the_machine_s_configuration_can_t_let_reading_reach_a_host(served, tmp_path, monkeypatch, shop):
    """`protocol.allow=never` is only a default: a `protocol.file.allow=always` in the machine's git configuration (a
    common workaround) would win over it. Every protocol is refused by name, so reading still fetches nothing."""
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text('[protocol "file"]\n\tallow = always\n')
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    cfg = remote_config(f"file://{served}/shop.git", tmp_path / "mirrors", refs=["main"])
    mirror = Mirror(cfg.repositories[0])
    mirror.sync()
    old_cart = git(served / "shop.git", "rev-parse", f"{shop[1]['start']}:src/shop/cart.py")
    monkeypatch.setattr(Mirror, "ensure", lambda self, wanted, git_dir=None: 0)
    text, error = await ask(cfg, "read_file", repo="shop", path="src/shop/cart.py", ref=shop[1]["start"])
    assert error and old_cart not in blobs_in(mirror.git_dir)
    # Each of the two layers holds alone. The command line: every protocol refused by name, with no help from the
    # environment.
    line = command(str(mirror.git_dir), ["cat-file", "blob", old_cart])
    done = subprocess.run(line, env=git_module.environment(), capture_output=True, check=False)
    assert done.returncode != 0 and old_cart not in blobs_in(mirror.git_dir)
    # The environment: GIT_NO_LAZY_FETCH, which git 2.44 and later (and patched older ones) obey whatever the
    # configuration says.
    seen: list[dict] = []
    real = subprocess.Popen

    def recording(args, *rest, **kwargs):
        seen.append(kwargs.get("env") or {})
        return real(args, *rest, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", recording)
    git_module.run(str(mirror.git_dir), ["rev-parse", "HEAD"])
    assert seen and seen[-1].get("GIT_NO_LAZY_FETCH") == "1"


def test_no_hook_of_the_machine_runs_during_a_sync(served, tmp_path, monkeypatch):
    """A `reference-transaction` hook the machine's configuration names would run on every ref the sync moves — with
    the token in its environment."""
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    ran = tmp_path / "hook-ran"
    hook = hooks / "reference-transaction"
    hook.write_text(f"#!/bin/sh\nenv > {ran}\n")
    hook.chmod(0o755)
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text(f"[core]\n\thooksPath = {hooks}\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("ACME_TOKEN", TOKEN)
    with GitHTTP(served, token=TOKEN) as host:
        cfg = remote_config(host.url("shop.git"), tmp_path / "mirrors", token_env="ACME_TOKEN")
        Mirror(cfg.repositories[0]).sync()
    assert not ran.exists()


async def test_a_diff_never_shows_a_folder_that_replaced_a_served_file(tmp_path):
    """A served file `config` replaced by a folder `config/` holding an excluded file: git, given the path `config`,
    takes the folder's files too. The excluded file's contents never show — nor reach a mirror."""
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-q", "-b", "main")
    write(source, "config", "served-file\n")
    write(source, "README.md", "hi\n")
    git(source, "add", "-A")
    git(source, "commit", "-q", "-m", "One", date="2026-04-01T10:00:00+00:00")
    git(source, "rm", "-q", "config")
    write(source, "config/prod.env", "API_KEY=made-up-top-secret\n")
    write(source, "config/app.yml", "port: 8080\n")
    git(source, "add", "-A")
    git(source, "commit", "-q", "-m", "Two", date="2026-04-02T10:00:00+00:00")
    remote = make_remote(source, tmp_path / "remotes" / "app.git")
    mirrored = remote_config(f"file://{remote}", tmp_path / "mirrors", exclude=["*.env"])
    mirror = Mirror(mirrored.repositories[0])
    mirror.sync()
    for cfg in (config_for(source, exclude=["*.env"]), mirrored):
        for tool, arguments in [("show_commit", {"commit": "main"}), ("diff", {"base": "main~1"})]:
            text, error = await ask(cfg, tool, repo="shop", **arguments)
            assert not error, (tool, text)
            assert "made-up-top-secret" not in text and "prod.env" not in text, text
            assert "+port: 8080" in text and "`config` is also a folder of files this server doesn't serve" in text
    assert git(remote, "rev-parse", "main:config/prod.env") not in blobs_in(mirror.git_dir)
    # Below the tools, too: a diff asked for `config` keeps the section of `config` alone.
    local = repository.Repository(config_for(source).repositories[0])
    out = local.patch("main~1", "main", [repository.Change("D", "config")], 100_000)
    assert b"served-file" in out.data and b"made-up-top-secret" not in out.data and b"app.yml" not in out.data


async def test_a_diff_shows_files_with_unusual_names(tmp_path):
    """The diff keeps the sections of the files asked for, however git writes their names (quoted, escaped)."""
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-q", "-b", "main")
    names = ["notes/план.md", 'odd "quoted" name.txt', "back\\slash.txt", "with space.txt"]
    for name in names:
        write(source, name, "one\n")
    write(source, "secret.env", "x\n")
    git(source, "add", "-A")
    git(source, "commit", "-q", "-m", "One", date="2026-04-01T10:00:00+00:00")
    for name in names:
        write(source, name, "two\n")
    git(source, "commit", "-q", "-am", "Two", date="2026-04-02T10:00:00+00:00")
    text, error = await ask(config_for(source, exclude=["*.env"]), "show_commit", repo="shop", commit="main")
    assert not error and text.count("+two") == len(names), text


async def test_a_contents_id_tells_nothing_as_a_ref(served, tmp_path, shop):
    """A file's id is its contents' digest. Given as a ref, the id of contents the mirror lacks (an excluded file's)
    answers as an unknown name does — so an agent can't confirm contents it guessed."""
    cfg = remote_config(f"file://{served}/shop.git", tmp_path / "mirrors", exclude=["secrets"])
    Mirror(cfg.repositories[0]).sync()
    secret = git(served / "shop.git", "rev-parse", f"{shop[1]['settings']}:secrets/prod.env")
    made_up = "0123456789abcdef0123456789abcdef01234567"
    known, _ = await ask(cfg, "read_file", repo="shop", path="README.md", ref=secret)
    unknown, _ = await ask(cfg, "read_file", repo="shop", path="README.md", ref=made_up)
    assert known.replace(secret, "X") == unknown.replace(made_up, "X")


def test_a_tag_of_a_folder_or_of_a_file_s_contents_is_not_kept(served, tmp_path, shop, monkeypatch):
    """A tag can name a folder (a tree) or a file's contents instead of a commit. Its paths are not the repository's
    — include / exclude could not judge them — so the mirror doesn't keep it, nor fetch the folder's contents."""
    remote = served / "shop.git"
    git(remote, "tag", "a-folder", f"{shop[1]['settings']}^{{tree}}")
    git(remote, "tag", "a-file", f"{shop[1]['settings']}:README.md")
    cfg = remote_config(f"file://{remote}", tmp_path / "mirrors", exclude=["secrets"])
    mirror = Mirror(cfg.repositories[0])
    mirror.sync()
    kept = git(mirror.git_dir, "for-each-ref", "--format=%(refname)")
    assert "refs/tags/a-folder" not in kept and "refs/tags/a-file" not in kept and "refs/tags/v0.1" in kept
    secret = git(remote, "rev-parse", f"{shop[1]['settings']}:secrets/prod.env")
    assert secret not in blobs_in(mirror.git_dir)
    commands: list[str] = []
    real = mirror_module.maintain

    def recording(git_dir, args, **kwargs):
        commands.append(args[0])
        return real(git_dir, args, **kwargs)

    monkeypatch.setattr(mirror_module, "maintain", recording)
    assert mirror.sync() == "up to date" and "fetch" not in commands  # dropped once, not fetched on every sync
    monkeypatch.setattr(mirror_module, "maintain", real)
    # And the files of what the sync reads are always listed from a commit's root — never from inside a folder.
    folder = git(remote, "rev-parse", f"{shop[1]['settings']}^{{tree}}")
    assert mirror._served_at(mirror.git_dir, [folder]) == []


def test_two_configurations_never_share_a_mirror(tmp_path, monkeypatch):
    """Two servers on one machine (a shared cache folder), or one configuration changed, get mirrors of their own: a
    mirror never holds branches or contents another configuration took — or fetched with another token."""
    monkeypatch.setenv("ACME_TOKEN", "made-up")

    def folder(**settings) -> str:
        return (
            remote_config("https://example.com/acme/shop.git", tmp_path / "mirrors", **settings).repositories[0].git_dir
        )

    assert folder() == folder()
    different = {folder(), folder(refs=["main"]), folder(exclude=["secrets"]), folder(include=["src"])}
    assert len(different | {folder(token_env="ACME_TOKEN"), folder(serve_credential_files=True)}) == 6
