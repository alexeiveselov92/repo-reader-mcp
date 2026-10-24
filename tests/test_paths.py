"""Paths an agent gives, and the include / exclude patterns."""

import pytest

from repo_reader_mcp.paths import Matcher, PathError, clean_path, compile_pattern


@pytest.mark.parametrize(
    ("given", "clean"),
    [("src/app.py", "src/app.py"), ("/src/app.py", "src/app.py"), ("src/", "src"), ("a b/c.txt", "a b/c.txt")],
)
def test_a_path_is_written_from_the_root(given, clean):
    assert clean_path(given) == clean


@pytest.mark.parametrize("given", ["../etc/passwd", "src/../../x", "./src", "src//app.py", "src/\napp.py", ""])
def test_a_path_that_is_not_plain_is_refused(given):
    with pytest.raises(PathError):
        clean_path(given)


def test_the_root_is_a_path_only_where_a_folder_is_asked_for():
    assert clean_path("", allow_root=True) == ""
    assert clean_path("/", allow_root=True) == ""


@pytest.mark.parametrize(
    ("pattern", "path", "hit"),
    [
        ("src/**", "src/a.py", True),
        ("src/**", "src/deep/er/a.py", True),
        ("src/**", "lib/src/a.py", False),
        ("src", "src/a.py", True),  # a folder takes what is in it
        ("*.pem", "keys/deep/prod.pem", True),  # no `/`: any depth
        ("/*.pem", "keys/prod.pem", False),  # a leading `/` anchors it to the root
        ("/*.pem", "prod.pem", True),
        ("**/fixtures/**", "data/fixtures/carts.json", True),
        ("**/fixtures/**", "fixtures/carts.json", True),
        ("docs/*.md", "docs/a.md", True),
        ("docs/*.md", "docs/sub/a.md", False),
        ("secrets", "app/secrets/key.txt", True),
        ("a?c.txt", "abc.txt", True),
        ("a?c.txt", "a/c.txt", False),
        ("[ab].txt", "a.txt", False),  # brackets are literal
        ("[ab].txt", "[ab].txt", True),
    ],
)
def test_patterns_follow_gitignore_habits(pattern, path, hit):
    assert Matcher(exclude=[pattern]).allows(path) is not hit


def test_include_takes_only_what_it_names_and_exclude_drops_from_it():
    matcher = Matcher(include=["src/**", "README.md"], exclude=["**/fixtures/**"])
    assert matcher.allows("src/app.py")
    assert matcher.allows("README.md")
    assert not matcher.allows("docs/guide.md")
    assert not matcher.allows("src/fixtures/a.json")


def test_without_include_or_exclude_everything_is_taken():
    assert Matcher().takes_everything
    assert Matcher().allows("anything/at/all")


@pytest.mark.parametrize("pattern", ["", "/", "src/../x", "a//b"])
def test_a_broken_pattern_is_refused(pattern):
    with pytest.raises(ValueError):
        compile_pattern(pattern)
