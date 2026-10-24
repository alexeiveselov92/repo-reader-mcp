"""The configuration file: what it accepts, and how a wrong entry stops the server, named."""

import pytest
from repos import git

from repo_reader_mcp.config import ConfigError, load_config, parse_config
from repo_reader_mcp.server import main


def problems(data, base) -> list[str]:
    with pytest.raises(ConfigError) as caught:
        parse_config(data, base)
    return caught.value.problems


def test_a_good_file_loads(shop, tmp_path):
    path, _ = shop
    file = tmp_path / "config.yaml"
    file.write_text(f"repositories:\n  - name: shop\n    path: {path}\n    description: A shop.\n")
    config = load_config(file)
    assert [r.name for r in config.repositories] == ["shop"]
    assert config.repositories[0].description == "A shop."
    assert config.limits.answer_characters == 40_000


def test_a_relative_path_is_taken_from_the_file_s_folder(shop):
    path, _ = shop
    file = path.parent / "config.yaml"
    file.write_text("repositories:\n  - name: shop\n    path: shop\n")
    assert load_config(file).repositories[0].path == str(path)


def test_a_bare_repository_is_served(shop, tmp_path):
    path, _ = shop
    git(tmp_path, "clone", "-q", "--bare", str(path), "shop.git")
    config = parse_config({"repositories": [{"name": "shop", "path": "shop.git"}]}, tmp_path)
    assert config.repositories[0].git_dir == str(tmp_path / "shop.git")


def test_an_unknown_key_is_named(shop):
    path, _ = shop
    found = problems({"repositories": [{"name": "shop", "path": str(path), "colour": "red"}]}, path.parent)
    assert found == ["repositories[0] (shop) → colour: an unknown key"]


def test_a_group_is_an_owner_and_a_pattern(tmp_path, monkeypatch):
    monkeypatch.setenv("ACME_TOKEN", "made-up")
    config = parse_config(
        {
            "repositories": [
                {"github": "acme/shop-*", "skip": ["shop-sandbox"], "exclude": ["*.pem"], "description": "The shop."},
                {"gitlab": "acme/backend/**/svc-*", "host": "git.example.com", "token_env": "ACME_TOKEN"},
            ]
        },
        tmp_path,
    )
    github, gitlab = config.groups
    assert (github.owner, github.pattern, github.host.api, github.label) == (
        "acme",
        "shop-*",
        "https://api.github.com",
        "github: acme/shop-*",
    )
    assert github.token_user == "x-access-token" and not github.subgroups
    assert (gitlab.owner, gitlab.pattern, gitlab.subgroups) == ("acme/backend", "**/svc-*", True)
    assert gitlab.host.api == "https://git.example.com/api/v4" and gitlab.token_user == "oauth2"
    assert gitlab.label == "gitlab: acme/backend/**/svc-* on git.example.com"
    assert config.repositories == []


def test_what_a_group_takes_and_skips(tmp_path):
    config = parse_config(
        {
            "repositories": [
                {"github": "acme/shop-*", "skip": ["shop-sandbox", "acme/shop-*-legacy"]},
                {"gitlab": "acme/backend/**"},
                {"gitlab": "acme/backend/*"},
            ]
        },
        tmp_path,
    )
    shop, deep, flat = config.groups
    assert shop.takes("acme/shop-api") and shop.takes("Acme/Shop-Web")  # hosts ignore letters' case
    assert not shop.takes("acme/billing") and not shop.takes("beta/shop-api")  # another owner, however it's spelt
    assert shop.skips("acme/shop-sandbox") and shop.skips("acme/shop-old-legacy") and not shop.skips("acme/shop-api")
    assert deep.takes("acme/backend/api") and deep.takes("acme/backend/team/api")
    assert flat.takes("acme/backend/api") and not flat.takes("acme/backend/team/api")
    assert deep.subgroups and not flat.subgroups  # GitLab is asked for subgroups' projects when the pattern reaches


def test_a_wrong_group_is_named(tmp_path, monkeypatch):
    monkeypatch.setenv("ACME_TOKEN", "made-up")
    cases = [
        ({"github": "acme/shop-*", "name": "shop"}, "a group takes none"),
        ({"github": "acme/team/shop-*"}, "github: `acme/team/shop-*` is not an owner and a pattern of names"),
        ({"github": "acme-*/shop"}, "names no owner"),
        ({"gitlab": "acme//x"}, "is not an owner and a pattern"),
        ({"github": "acme/shop-*", "skip": ["other/shop-x"]}, "skip[0]: `other/shop-x` is not a repository of `acme`"),
        ({"github": "acme/*", "url": "https://example.com/a/b.git"}, "give one of `path`, `url`, `github`, `gitlab`"),
        ({"url": "https://example.com/a/web.git", "skip": ["x"]}, "skip: it goes with a group"),
        ({"github": "acme/*", "host": "http://git.example.com", "token_env": "ACME_TOKEN"}, "over https only"),
        ({"github": "acme/*", "host": "ftp://git.example.com"}, "a host's address is https://"),
        ({"github": "acme/*", "token_env": "UNSET_MADE_UP_TOKEN"}, "is not set in the server's environment"),
        ({"github": "acme/*", "host": "https://git.example.com:abc"}, "has a port that is not a number"),
        ({"github": "acme/*", "listed": False}, "`listed: false` would serve nothing"),
    ]
    for entry, says in cases:
        found = problems({"repositories": [entry]}, tmp_path)
        assert len(found) == 1 and says in found[0], (entry, found)


def test_guidance_comes_from_a_repository_listed_one_by_one(shop, tmp_path):
    path, _ = shop
    rules = {"name": "rules", "path": str(path)}
    group = {"github": "acme/shop-*", "guidance": {"from": [{"repo": "rules"}]}}
    assert parse_config({"repositories": [rules, group]}, tmp_path).groups[0].guidance.sources[0].repo == "rules"
    found = problems({"repositories": [{**group, "guidance": {"from": [{"repo": "shop-api"}]}}]}, tmp_path)
    assert "a group's repository can't be a source" in found[0]


@pytest.mark.parametrize(
    ("url", "name"),
    [
        ("https://example.com/acme/shop-web.git", "shop-web"),
        ("https://example.com/acme/shop-web", "shop-web"),
        ("ssh://git@example.com/acme/shop-web.git", "shop-web"),
        ("git@example.com:acme/shop-web.git", "shop-web"),
        ("file:///srv/remotes/shop-web.git", "shop-web"),
    ],
)
def test_a_remote_repository_is_named_from_its_url(tmp_path, url, name):
    config = parse_config({"repositories": [{"url": url}], "mirrors": {"folder": "mirrors"}}, tmp_path)
    repo = config.repositories[0]
    assert repo.name == name and repo.remote.url == url
    assert repo.git_dir.startswith(str(tmp_path / "mirrors" / f"{name}-")) and repo.git_dir.endswith(".git")


@pytest.mark.parametrize(
    ("url", "says"),
    [
        ("https://acme:hunter2@example.com/acme/web.git", "can't carry credentials"),
        ("https://made-up-token@example.com/acme/web.git", "can't carry credentials"),
        ("ext::sh -c touch% /tmp/pwned", "spaces or control characters"),
        ("ext::sh", "remote helpers"),
        ("ftp://example.com/acme/web.git", "not a protocol this server fetches by"),
        ("/srv/code/web", "is given by `path`"),
        ("https:///acme/web.git", "names no host"),
        ("https://example.com/acme/web.git?private_token=made-up", "can't carry a query"),
        ("https://example.com/acme/web.git#main", "can't carry a query"),
    ],
)
def test_a_url_that_can_t_be_served_is_named(tmp_path, url, says):
    found = problems({"repositories": [{"name": "web", "url": url}]}, tmp_path)
    assert found[0].startswith("repositories[0] (web) → url:") and says in found[0], found


def test_a_token_is_named_by_its_variable_and_must_be_set(tmp_path, monkeypatch):
    monkeypatch.delenv("ACME_TOKEN", raising=False)
    entry = {"url": "https://example.com/acme/web.git", "token_env": "ACME_TOKEN"}
    found = problems({"repositories": [entry]}, tmp_path)
    assert found == [
        "repositories[0] (web) → token_env: the variable ACME_TOKEN is not set in the server's environment"
    ]
    monkeypatch.setenv("ACME_TOKEN", "made-up")
    repo = parse_config({"repositories": [entry]}, tmp_path).repositories[0]
    assert repo.remote.token_env == "ACME_TOKEN" and repo.remote.token_user == "x-access-token"
    assert "made-up" not in repr(repo)  # the configuration holds the name, never the value
    found = problems({"repositories": [{**entry, "token_env": "not a variable"}]}, tmp_path)
    assert found[0].startswith("repositories[0] (web) → token_env:")


def test_remote_keys_belong_to_remote_repositories(shop, tmp_path, monkeypatch):
    path, _ = shop
    monkeypatch.setenv("ACME_TOKEN", "made-up")
    cases = [
        ({"name": "shop", "path": str(path), "refs": ["main"]}, "refs: it is for a remote repository"),
        ({"name": "shop", "path": str(path), "url": "https://example.com/a/shop.git"}, "not `path` and `url`"),
        ({"name": "shop"}, "give `path`"),
        ({"url": "ssh://git@example.com/a/web.git", "token_env": "ACME_TOKEN"}, "a token goes with an https url"),
        ({"url": "https://example.com/a/web.git", "token_user": "bot"}, "token_user: it goes with `token_env`"),
        ({"url": "https://example.com/"}, "none can be taken from its url"),
        ({"url": "http://example.com/a/web.git", "token_env": "ACME_TOKEN"}, "a token is sent over https only"),
    ]
    for entry, says in cases:
        found = problems({"repositories": [entry]}, tmp_path)
        assert len(found) == 1 and says in found[0], (entry, found)


def test_how_often_mirrors_are_synced_is_bounded(tmp_path):
    entry = {"url": "https://example.com/a/web.git"}
    assert parse_config({"repositories": [entry]}, tmp_path).mirrors.every_minutes == 10
    found = problems({"repositories": [entry], "mirrors": {"every_minutes": -1}}, tmp_path)
    assert found[0].startswith("mirrors → every_minutes:")


def test_a_missing_folder_and_a_folder_that_is_no_repository_are_named(shop, tmp_path):
    path, _ = shop
    (tmp_path / "empty").mkdir()
    data = {"repositories": [{"name": "gone", "path": "nowhere"}, {"name": "plain", "path": "empty"}]}
    found = problems(data, tmp_path)
    assert len(found) == 2  # every problem at once
    assert found[0].startswith("repositories[0] (gone) → path:") and "is not a folder" in found[0]
    assert found[1].startswith("repositories[1] (plain) → path:") and "not a git repository" in found[1]


def test_a_folder_inside_a_repository_is_refused(shop):
    path, _ = shop
    found = problems({"repositories": [{"name": "src", "path": str(path / "src")}]}, path.parent)
    assert "inside the repository" in found[0]


def test_names_must_be_plain_and_unique(shop):
    path, _ = shop
    data = {"repositories": [{"name": "shop", "path": str(path)}, {"name": "shop", "path": str(path)}]}
    assert problems(data, path.parent) == ["repositories[1] (shop) → name: `shop` is used by an earlier repository"]
    found = problems({"repositories": [{"name": "my shop", "path": str(path)}]}, path.parent)
    assert "a name is up to 100 letters" in found[0]


def test_a_broken_pattern_is_named(shop):
    path, _ = shop
    found = problems({"repositories": [{"name": "shop", "path": str(path), "exclude": ["a/../b"]}]}, path.parent)
    assert found[0].startswith("repositories[0] (shop) → exclude:")


def test_the_file_needs_repositories_and_sane_limits(shop):
    path, _ = shop
    assert "repositories" in problems({"repositories": []}, path.parent)[0]
    found = problems(
        {"repositories": [{"name": "s", "path": str(path)}], "limits": {"answer_characters": 10}}, path.parent
    )
    assert found[0].startswith("limits → answer_characters:")


def test_broken_yaml_names_the_line(tmp_path):
    file = tmp_path / "config.yaml"
    file.write_text("repositories:\n  - name: [unclosed\n")
    with pytest.raises(ConfigError) as caught:
        load_config(file)
    assert "not valid YAML at line" in caught.value.problems[0]


def test_the_server_stops_on_a_wrong_file_and_says_why(tmp_path, capsys):
    file = tmp_path / "config.yaml"
    file.write_text("repositories:\n  - name: shop\n    path: nowhere\n")
    with pytest.raises(SystemExit) as stopped:
        main(["--config", str(file)])
    assert stopped.value.code == 2
    assert "repositories[0] (shop) → path:" in capsys.readouterr().err


def test_the_server_needs_a_configuration(capsys, monkeypatch):
    monkeypatch.delenv("REPO_READER_MCP_CONFIG", raising=False)
    with pytest.raises(SystemExit) as stopped:
        main([])
    assert stopped.value.code == 2
    assert "--config" in capsys.readouterr().err


def test_check_lists_what_is_served(shop, tmp_path, capsys):
    path, _ = shop
    file = tmp_path / "config.yaml"
    file.write_text(f"repositories:\n  - name: shop\n    path: {path}\n")
    main(["--config", str(file), "--check"])
    out = capsys.readouterr().out
    assert "is good — it serves 1 repository:" in out
    assert "shop" in out
