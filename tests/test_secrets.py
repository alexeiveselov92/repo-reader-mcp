"""Secrets found in what a repository holds are hidden in every answer, and files named for credentials are never
served — the made-up values below are made up, and shaped like the real thing only so the rules see them.
"""

import pytest
from conftest import ask
from remotes import blobs_in, contents_by_path, make_remote
from repos import ALAN, commit, git, write

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
    for config in (served(leaky, tmp_path), served(leaky, tmp_path, serve_credential_files=True)):
        text, _ = await ask(config, "log", repo="leaky", message=GITHUB_TOKEN[:12])  # held back or not: both ways
        assert "Add the config" not in text, text
    config = served(leaky, tmp_path)
    text, _ = await ask(config, "log", repo="leaky", message="config|rotate")  # an extended regex
    assert "Add the config" in text and "Rotate the password" in text


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
