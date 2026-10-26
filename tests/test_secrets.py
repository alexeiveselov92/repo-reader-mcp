"""Secrets found in what a repository holds are hidden in every answer, and files named for credentials are never
served — the made-up values below are made up, and shaped like the real thing only so the rules see them.
"""

import pytest
from conftest import ask
from remotes import blobs_in, contents_by_path, make_remote
from repos import ALAN, commit, git, write

from repo_reader_mcp import git as git_module
from repo_reader_mcp import tools
from repo_reader_mcp.config import parse_config
from repo_reader_mcp.secrets import hide

pytestmark = pytest.mark.anyio

GITHUB_TOKEN = "ghp_" + "Ab12" * 9
KEY_BODY = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKj"  # 64 characters, as a PEM line
PRIVATE_KEY = "\n".join(
    [
        "-----BEGIN PRIVATE KEY-----",
        KEY_BODY,
        KEY_BODY.lower().upper()[:63] + "x",
        "ZmFrZQ==",
        "-----END PRIVATE KEY-----",
    ]
)
CONFIG = f'''service:
  name: shop
  github_token: "{GITHUB_TOKEN}"
  database: postgres://shop:s3cret-Pass@db.example.com/shop
  password: hunter2024
  max_tokens: 100000
'''


@pytest.fixture
def leaky(tmp_path):
    """A repository that committed what it shouldn't have."""
    repo = tmp_path / "leaky"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "config.yml", CONFIG)
    write(repo, "deploy/key.txt", "Our deploy key:\n" + PRIVATE_KEY + "\nthat's all\n")
    write(repo, ".env", "API_TOKEN=made-up-env-value-123\n")
    write(repo, ".env.example", "API_TOKEN=\n")
    write(repo, "certs/server.pem", PRIVATE_KEY + "\n")
    write(repo, "README.md", "Run it. The admin password is Qwerty!2026 for now.\n")
    commit(repo, f"Add the config (token {GITHUB_TOKEN})", ALAN, "2026-03-01T10:00:00+00:00")
    write(repo, "config.yml", CONFIG.replace("hunter2024", "hunter2025"))
    commit(repo, "Rotate the password", ALAN, "2026-03-02T10:00:00+00:00")
    return repo


def served(repo, tmp_path, **settings):
    return parse_config({"repositories": [{"name": "leaky", "path": str(repo), **settings}]}, tmp_path)


async def test_read_file_hides_secrets_and_says_how_many(leaky, tmp_path):
    text, error = await ask(served(leaky, tmp_path), "read_file", repo="leaky", path="config.yml")
    assert not error
    for secret in (GITHUB_TOKEN, "s3cret-Pass", "hunter2025"):
        assert secret not in text
    assert 'github_token: "[hidden: GitHub token]"' in text and "max_tokens: 100000" in text
    assert "postgres://shop:[hidden: password]@db.example.com/shop" in text
    assert "[3 values that look like secrets are hidden as `[hidden: …]` — this server never shows them.]" in text


async def test_a_private_key_is_hidden_whole_wherever_the_window_starts(leaky, tmp_path):
    config = served(leaky, tmp_path)
    for start in (1, 4):
        text, _ = await ask(config, "read_file", repo="leaky", path="deploy/key.txt", start_line=start)
        assert KEY_BODY not in text and "ZmFrZQ==" not in text and "[hidden: private key]" in text
    text, _ = await ask(config, "blame", repo="leaky", path="deploy/key.txt")
    assert KEY_BODY not in text and "ZmFrZQ==" not in text and "that's all" in text


async def test_diffs_messages_and_search_hide_them_too(leaky, tmp_path):
    config = served(leaky, tmp_path)
    text, _ = await ask(config, "show_commit", repo="leaky", commit="main")
    assert "hunter2024" not in text and "hunter2025" not in text
    text, _ = await ask(config, "log", repo="leaky")
    assert GITHUB_TOKEN not in text and "token [hidden: GitHub token]" in text
    text, _ = await ask(config, "search", pattern="password")
    assert "Qwerty!2026" not in text and "hunter2025" not in text and "README.md" in text
    text, _ = await ask(config, "grep", repo="leaky", pattern="END PRIVATE", context=1)
    assert "ZmFrZQ==" not in text and "[hidden: private key]" in text  # a key's last line, short: hidden by its block


async def test_an_error_carries_no_secret_either(leaky, tmp_path, monkeypatch):
    from repo_reader_mcp.repository import ReadError, Repository

    def failing(self, entry, limit):
        raise ReadError(f"git could not read it: fatal: bad line {GITHUB_TOKEN}")

    monkeypatch.setattr(Repository, "blob", failing)
    text, error = await ask(served(leaky, tmp_path), "read_file", repo="leaky", path="config.yml")
    assert error and GITHUB_TOKEN not in text and "[hidden: GitHub token]" in text


async def test_a_guessed_secret_can_t_be_confirmed_by_searching_for_it(leaky, tmp_path):
    config = served(leaky, tmp_path)
    for pattern, regex in (("hunter2025", False), ("s3cret-P.ss", True), (KEY_BODY[:20], False)):
        text, error = await ask(config, "grep", repo="leaky", pattern=pattern, regex=regex)
        assert not error and "no line matches" in text, (pattern, text)
        text, _ = await ask(config, "search", pattern=pattern, regex=regex)
        assert "no line matches" in text, (pattern, text)


async def test_a_guessed_secret_can_t_be_confirmed_by_searching_messages(leaky, tmp_path):
    for config in (served(leaky, tmp_path), served(leaky, tmp_path, exclude=["nothing-here"])):
        text, _ = await ask(config, "log", repo="leaky", message=GITHUB_TOKEN[:12])  # held back or not: both ways
        assert "Add the config" not in text, text
        text, _ = await ask(config, "search_commits", message=GITHUB_TOKEN[:12])
        assert "no commit matches" in text, text
    config = served(leaky, tmp_path)
    for tool, extra in (("log", {"repo": "leaky"}), ("search_commits", {})):
        text, _ = await ask(config, tool, message="config|rotate", **extra)  # an extended regex
        assert "Rotate the password" in text and "Add the config" not in text, tool  # its message holds a secret


async def test_files_named_for_credentials_are_never_served(leaky, tmp_path):
    config = served(leaky, tmp_path)
    text, _ = await ask(config, "list_files", repo="leaky", recursive=True)
    assert ".env.example" in text and "\n.env\n" not in text and "server.pem" not in text
    text, error = await ask(config, "read_file", repo="leaky", path=".env")
    assert error and "outside what this server serves" in text
    text, _ = await ask(config, "search", pattern="made-up-env-value")
    assert "no line matches" in text
    text, _ = await ask(served(leaky, tmp_path, serve_credential_files=True), "read_file", repo="leaky", path=".env")
    assert "API_TOKEN=[hidden: secret value]" in text  # served on purpose — its secrets still hidden


async def test_a_mirror_never_fetches_files_named_for_credentials(leaky, tmp_path):
    from repo_reader_mcp.mirror import Mirror

    remote = make_remote(leaky, tmp_path / "remotes" / "leaky.git")
    data = {"repositories": [{"name": "leaky", "url": f"file://{remote}"}], "mirrors": {"folder": str(tmp_path / "m")}}
    mirror = Mirror(parse_config(data, tmp_path).repositories[0])
    mirror.sync()
    credentials = {oid for oid, path in contents_by_path(remote) if path in (".env", "certs/server.pem")}
    assert credentials and not credentials & blobs_in(mirror.git_dir)


def test_what_is_hidden_and_what_is_not():
    for line in (
        'aws = "AKIAIOSFODNN7EXAMPLE"',
        "SLACK_BOT=xoxb-123456789012-abcdefABCDEF",
        "ANTHROPIC_API_KEY=sk-ant-api03-" + "x1" * 20,
        "DB_PASSWORD=qwerty123",
        "bot 123456789:AA" + "b" * 33,
        KEY_BODY,
    ):
        assert "[hidden: " in hide(line), line
    for line in (
        "token = get_token()",
        "password: str",
        "SECRET_KEY = os.environ['SECRET_KEY']",
        "password=${DB_PASSWORD}",
        "commit 18808c69612105fda1c152326173acb346ce0a61",
        'hash = "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"',
        "password: changeme",
        "max_tokens: 100000",
    ):
        assert hide(line) == line, line


# --- the refuting review's findings ---------------------------------------------------------------------------------

KUBE_KEY = "LS0tLS1CRUdJTiBFQyBQUklWQVRFIEtFWS0tLS0tCk1IY0NBUUVFSUJhZGtleWJ5dGVzbWFkZXVw" * 4
LONG_LINE = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKjMzEfYyjiWA4R4/M2"  # 76, as base64 wraps


@pytest.fixture
def oracle(tmp_path):
    repo = tmp_path / "oracle"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "a.yml", 'alpha\npassword: "Sup3rS3cretVal"\nomega\n')
    write(repo, "b.yml", 'password: "hunter2024"\nprint("hello")\n')
    write(repo, "c.yml", 'password: "zebra20245"\nprint("hello")\n')
    write(repo, "kube.yml", f"users:\n- user:\n    client-key-data: {KUBE_KEY}\n")
    write(repo, "urls.txt", "cache: redis://:Sup3rS3cretPw@cache.example.com:6379/0\n"
          "DATABASE_URL=postgres://shop:p@ss-W0rd@db.example.com/shop\n")  # fmt: skip
    write(repo, "code.py", "PEM_HEADER = '-----BEGIN RSA PRIVATE KEY-----'\nVERSION\ndef parse():\n    return 1\n")
    commit(repo, "files", ALAN, "2026-03-01T10:00:00+00:00")
    write(repo, "deploy.pem.txt", "-----BEGIN PRIVATE KEY-----\n" + LONG_LINE + "\n" + LONG_LINE + "\nAbCd12==\n"
          "-----END PRIVATE KEY-----\n")  # fmt: skip
    commit(repo, f"Add the deploy key (token {GITHUB_TOKEN})", ALAN, "2026-03-02T10:00:00+00:00")
    return parse_config({"repositories": [{"name": "oracle", "path": str(repo)}]}, tmp_path)


async def answers(config, tool, **arguments):
    """An answer with the agent's own pattern (which the answer repeats) put aside, to compare two guesses by."""
    text, _ = await ask(config, tool, **arguments)
    for key in ("pattern", "message"):
        if key in arguments:
            text = text.replace(arguments[key], "<the pattern>")
    return text


async def test_a_regex_can_t_tell_a_right_guess_from_a_wrong_one(oracle):
    pairs = [
        ('""|hunter2024', '""|hunter2025'),
        ('^password: ""$|password: "h', '^password: ""$|password: "x'),
        ("(.|.)*Z|Sup3rS3cretVal", "(.|.)*Z|Wrong0Guess"),
    ]
    for right, wrong in pairs:
        for tool, extra in (("grep", {"repo": "oracle"}), ("search", {})):
            assert await answers(oracle, tool, pattern=right, regex=True, **extra) == await answers(
                oracle, tool, pattern=wrong, regex=True, **extra
            ), (tool, right)


async def test_lines_around_a_match_and_files_only_tell_nothing_either(oracle):
    right = await answers(oracle, "grep", repo="oracle", pattern="alpha|Sup3rS3cretVal", regex=True, context=1)
    wrong = await answers(oracle, "grep", repo="oracle", pattern="alpha|Wrong0Guess", regex=True, context=1)
    assert right == wrong
    text = await answers(oracle, "grep", repo="oracle", pattern='"h', files_only=True)
    assert "b.yml" in text and "c.yml" in text  # both hold `print("hello")`, whatever their secret starts with


async def test_log_by_message_can_t_confirm_a_guess(oracle):
    for right, wrong in (("token \\)|ghp_Ab12", "token \\)|ghp_Zz99"), ("ghp_Ab12(x**)?", "ghp_Zz99(x**)?")):
        assert await answers(oracle, "log", repo="oracle", message=right) == await answers(
            oracle, "log", repo="oracle", message=wrong
        )
        assert await answers(oracle, "search_commits", message=right) == await answers(
            oracle, "search_commits", message=wrong
        )


async def test_a_guess_never_shifts_what_a_history_by_message_shows(tmp_path, monkeypatch):
    """A commit whose message holds a secret is left out before the answer is cut, never after: a guess that matches
    it shows the same commits — and says the same about more to follow — as a guess that doesn't."""
    repo = tmp_path / "notes"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    for day, message in enumerate(["note 1", "note 2", f"Add the key (token {GITHUB_TOKEN})", "note 3"], start=1):
        write(repo, "notes.txt", message + "\n")
        commit(repo, message, ALAN, f"2026-03-0{day}T10:00:00+00:00")
    config = parse_config({"repositories": [{"name": "notes", "path": str(repo)}]}, tmp_path)
    right, wrong = "note|ghp_Ab12", "note|ghp_Zz99"
    for skip in (0, 1):
        assert await answers(config, "log", repo="notes", message=right, max_count=2, skip=skip) == await answers(
            config, "log", repo="notes", message=wrong, max_count=2, skip=skip
        ), skip
    monkeypatch.setattr(tools, "COMMITS_PER_REPO", 2)
    assert await answers(config, "search_commits", message=right) == await answers(
        config, "search_commits", message=wrong
    )


@pytest.fixture
def tricky(tmp_path):
    """Messages written to slip past the check of what a message holds: a separator before the secret, another
    commit's id between separators (anyone who can push can write one), a message longer than is read at once."""
    repo = tmp_path / "tricky"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "a.txt", "1\n")
    secret = commit(repo, f"Rotate things\n\nsee \x01 token {GITHUB_TOKEN}", ALAN, "2026-03-01T10:00:00+00:00")
    write(repo, "a.txt", "2\n")
    commit(repo, f"zz-unlock \x01{secret}\x01 \x1e{secret}\x1f", ALAN, "2026-03-02T10:00:00+00:00")
    write(repo, "a.txt", "3\n")
    commit(repo, "long " + "words " * 400 + f"\n\ntoken {GITHUB_TOKEN}", ALAN, "2026-03-03T10:00:00+00:00")
    return parse_config({"repositories": [{"name": "tricky", "path": str(repo)}]}, tmp_path)


async def test_a_message_can_t_slip_past_the_check_of_what_it_holds(tricky, monkeypatch):
    monkeypatch.setattr(git_module, "OUTPUT_BYTES", 1500)  # the long message is longer than is read at once
    for right, wrong in (
        ("ghp_Ab12", "ghp_Zz99"),
        ("zz-unlock|ghp_Ab12", "zz-unlock|ghp_Zz99"),
        ("long|ghp_Ab", "long|ghp_Zz"),
    ):
        for tool, extra in (("log", {"repo": "tricky"}), ("search_commits", {})):
            assert await answers(tricky, tool, message=right, **extra) == await answers(
                tricky, tool, message=wrong, **extra
            ), (tool, right)
    text, _ = await ask(tricky, "search_commits", message="zz-unlock|rotate")
    assert "zz-unlock" in text and "Rotate things" not in text


async def test_keys_on_one_line_in_diffs_and_in_urls_are_hidden(oracle):
    text = await answers(oracle, "read_file", repo="oracle", path="kube.yml")
    assert KUBE_KEY[:30] not in text and "client-key-data: [hidden:" in text
    text = await answers(oracle, "show_commit", repo="oracle", commit="main")
    assert LONG_LINE not in text and "AbCd12==" not in text and "+[hidden: private key]" in text
    text = await answers(oracle, "read_file", repo="oracle", path="urls.txt")
    assert "Sup3rS3cretPw" not in text and "p@ss-W0rd" not in text and "ss-W0rd" not in text
    assert "redis://:[hidden: password]@cache.example.com" in text and "postgres://shop:[hidden: password]@db" in text


async def test_a_marker_in_code_hides_nothing_after_it(oracle):
    text = await answers(oracle, "read_file", repo="oracle", path="code.py")
    assert "VERSION" in text and "def parse():" in text and "[hidden" not in text


async def test_hiding_never_pushes_an_answer_past_its_limit(tmp_path):
    repo = tmp_path / "many"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "a.txt", "x\n")
    commit(repo, "start", ALAN, "2026-03-01T10:00:00+00:00")
    write(repo, "a.txt", "".join(f'pwd:"a{i:05}"\n' for i in range(5000)))
    commit(repo, "many", ALAN, "2026-03-02T10:00:00+00:00")
    config = parse_config(
        {"repositories": [{"name": "many", "path": str(repo)}], "limits": {"answer_characters": 20000}}, tmp_path
    )
    text = await answers(config, "show_commit", repo="many", commit="main")
    assert len(text) <= 20000 and "[hidden: secret value]" in text


def test_the_last_filter_keeps_an_answer_within_its_limit():
    from repo_reader_mcp.tools import shown

    text = shown('pwd:"a00001"\n' * 1500, 20000)  # each mark longer than the value it hides
    assert len(text) <= 20000 and "[cut: hiding secrets made the answer longer than fits]" in text


async def test_one_repository_that_fails_doesn_t_stop_a_search(oracle, shop, monkeypatch):
    import repo_reader_mcp.git as git_module

    config = parse_config(
        {
            "repositories": [
                {"name": "oracle", "path": str(oracle.repositories[0].path)},
                {"name": "shop", "path": str(shop[0])},
            ]
        },
        shop[0].parent,
    )
    real = git_module.subprocess.Popen

    def popen(cmd, *args, **kwargs):
        if "grep" in cmd and str(oracle.repositories[0].git_dir) in " ".join(map(str, cmd)):
            raise OSError(7, "Argument list too long")
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(git_module.subprocess, "Popen", popen)
    text = await answers(config, "search", pattern="currency")
    assert "## shop" in text and "(oracle was not searched:" in text and "Argument list too long" in text


async def test_names_and_lines_that_are_not_secrets_stay(oracle):
    for line in (
        '"forgot_password": "Forgot your password?"',
        "token_url: https://oauth.example.com/oauth/token",
        "tokenizer: bert-base-uncased",
        'raise ValueError("password is invalid")',
        'TOKEN_STORAGE_KEY = "access_token"',
        "SRC = src/main/kotlin/com/acme/shop/checkout/v2/PaymentGatewayController",
        "integrity sha512-z4PhNX7vuL3xVChQ1m2AB9Yg5AULVxXcg/SpIdNs6c5H0NE8XYXysP+DGNKHfuwvY7kxvUdBeoGlODJ6+SfaPg==",
    ):
        assert hide(line) == line, line


def test_more_files_named_for_credentials():
    from repo_reader_mcp.paths import Matcher

    matcher = Matcher(credentials=True)
    for path in (
        "prod.env",
        "x/.envrc",
        "id_rsa_github",
        ".git-credentials",
        "keys/putty.ppk",
        "infra/terraform.tfstate",
    ):
        assert not matcher.allows(path), path
    for path in (".env.example", "id_rsa.pub", "src/env.py", "README.md"):
        assert matcher.allows(path), path


async def test_list_files_doesn_t_walk_the_whole_tree_for_credential_files(leaky, tmp_path, monkeypatch):
    from repo_reader_mcp.repository import Repository

    asked = []
    children = Repository.children

    def listed(self, at, folder=""):
        asked.append(folder)
        return children(self, at, folder)

    monkeypatch.setattr(Repository, "children", listed)
    text, error = await ask(served(leaky, tmp_path), "list_files", repo="leaky")
    assert not error and ".env.example" in text and "\n.env\n" not in text
    assert asked == [""]  # the folder's own entries, not every file under it


def test_each_way_a_key_on_one_line_is_seen():
    blob = "Zm9vYmFyQmF6UXV4" * 8 + "Q9xR2"  # 133 characters of mixed base64, not a key's header
    assert hide(f"data: {blob}") == "data: [hidden: key material]"
    assert hide("x: LS0tLS1CRUdJTiBQUklWQVRF") == "x: [hidden: private key]"  # short: its header gives it away


async def test_a_history_without_include_exclude_doesn_t_walk_every_commit(leaky, tmp_path, monkeypatch):
    from repo_reader_mcp.repository import Repository

    walks = []
    log = Repository.log

    def recorded(self, *args, **kwargs):
        walks.append(kwargs.get("with_paths", False))
        return log(self, *args, **kwargs)

    monkeypatch.setattr(Repository, "log", recorded)
    text, error = await ask(served(leaky, tmp_path), "log", repo="leaky")
    assert not error and walks == [False]
