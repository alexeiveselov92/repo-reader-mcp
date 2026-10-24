"""Links to a host's own pages: built from the repository's address and a commit id, in each host's own form."""

import pytest

from repo_reader_mcp.links import links_for

C = "14a4c0422ae3f00d"


@pytest.mark.parametrize(
    ("url", "kind", "base"),
    [
        ("https://github.com/acme/shop.git", None, "https://github.com/acme/shop"),
        ("git@github.com:acme/shop.git", None, "https://github.com/acme/shop"),
        ("ssh://git@gitlab.com:2222/acme/team/shop.git", None, "https://gitlab.com/acme/team/shop"),
        ("https://bitbucket.org/acme/shop", None, "https://bitbucket.org/acme/shop"),
        ("https://git.example.com:8443/tools/shop.git", "gitlab", "https://git.example.com:8443/tools/shop"),
        ("https://example.com/gitlab/acme/shop.git", "gitlab", "https://example.com/gitlab/acme/shop"),
        ("http://127.0.0.1:8000/acme/shop.git", "github", "http://127.0.0.1:8000/acme/shop"),
    ],
)
def test_a_repository_s_page(url, kind, base):
    links = links_for(url, kind)
    assert links is not None and links.base == base


@pytest.mark.parametrize(
    ("url", "kind"),
    [
        ("https://git.example.com/acme/shop.git", None),  # a host of unknown kind
        ("https://github.com/acme/shop.git", "none"),  # links turned off
        ("file:///srv/remotes/shop.git", "github"),
        ("https://github.com/", None),
    ],
)
def test_no_links_where_nothing_tells(url, kind):
    assert links_for(url, kind) is None


def test_each_host_s_own_forms():
    github = links_for("https://github.com/acme/shop.git")
    gitlab = links_for("https://gitlab.com/acme/shop.git")
    bitbucket = links_for("https://bitbucket.org/acme/shop.git")
    assert github.file(C, "src/a b.py", 3, 9) == f"https://github.com/acme/shop/blob/{C}/src/a%20b.py#L3-L9"
    assert gitlab.file(C, "src/app.py", 3, 9) == f"https://gitlab.com/acme/shop/-/blob/{C}/src/app.py#L3-9"
    assert bitbucket.file(C, "src/app.py", 3, 9) == f"https://bitbucket.org/acme/shop/src/{C}/src/app.py#lines-3:9"
    assert github.file(C, "README.md", 1, 1) == f"https://github.com/acme/shop/blob/{C}/README.md#L1"
    assert github.folder(C) == f"https://github.com/acme/shop/tree/{C}"
    assert gitlab.folder(C, "src") == f"https://gitlab.com/acme/shop/-/tree/{C}/src"
    assert github.commit(C) == f"https://github.com/acme/shop/commit/{C}"
    assert gitlab.commit(C) == f"https://gitlab.com/acme/shop/-/commit/{C}"
    assert bitbucket.commit(C) == f"https://bitbucket.org/acme/shop/commits/{C}"
    assert github.compare("aaa", "bbb") == "https://github.com/acme/shop/compare/aaa...bbb"
    assert bitbucket.compare("aaa", "bbb") is None
