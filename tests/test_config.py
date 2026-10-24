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


def test_remote_keys_say_they_come_later(shop):
    path, _ = shop
    found = problems({"repositories": [{"name": "web", "url": "https://example.com/acme/web.git"}]}, path.parent)
    assert any("url" in p and "not supported yet" in p for p in found)


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
