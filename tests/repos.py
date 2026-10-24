"""Made-up repositories the tests build with real git: fixed authors and dates, no network.

`build_shop` makes a small shop's history: branches, an annotated and a lightweight tag, a merge, a deletion, a binary
file, a link, a long file and a minified one-line file, a folder of made-up secrets for `exclude` to keep out — and
changes left uncommitted in the checkout, which the server must never show.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ADA = ("Ada Lovelace", "ada@example.com")
GRACE = ("Grace Hopper", "grace@example.com")
ALAN = ("Alan Turing", "alan@example.com")


def git_env(author: tuple[str, str] = ADA, date: str = "2026-01-01T09:00:00+00:00") -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME=author[0],
        GIT_AUTHOR_EMAIL=author[1],
        GIT_COMMITTER_NAME=author[0],
        GIT_COMMITTER_EMAIL=author[1],
        GIT_AUTHOR_DATE=date,
        GIT_COMMITTER_DATE=date,
    )
    return env


def git(
    repo: Path,
    *args: str,
    author: tuple[str, str] = ADA,
    date: str = "2026-01-01T09:00:00+00:00",
    data: bytes | None = None,
) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], env=git_env(author, date), input=data, capture_output=True, check=True
    )
    return done.stdout.decode().strip()


def write(repo: Path, path: str, content: str | bytes) -> None:
    file = repo / path
    file.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        file.write_bytes(content)
    else:
        file.write_text(content, encoding="utf-8")


def commit(repo: Path, message: str, author: tuple[str, str], date: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message, author=author, date=date)
    return git(repo, "rev-parse", "HEAD")


CART_V1 = '''"""The cart. Money is kept in cents, as integers."""


class Cart:
    def __init__(self):
        self.items = []

    def add(self, sku, price_cents, quantity=1):
        self.items.append((sku, price_cents, quantity))

    def total(self):
        return sum(price * quantity for _, price, quantity in self.items)
'''

CART_V2 = CART_V1.replace(
    "    def total(self):\n        return sum(",
    "    def total(self):\n        if not self.items:\n            return 0\n        return sum(",
)

PRICING_V1 = '''"""Prices for the cart, in cents."""

TAX_RATE = 0.2


def with_tax(cents):
    return round(cents * (1 + TAX_RATE))
'''

PRICING_V2 = (
    PRICING_V1
    + '''

def discounted(cents, percent):
    """A discount of `percent` percent, rounded to a cent."""
    return round(cents * (100 - percent) / 100)
'''
)


def build_shop(repo: Path) -> dict[str, str]:
    """The made-up shop at `repo`; returns its commits by name."""
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    ids = {}

    write(repo, "README.md", "# Acme shop\n\nA made-up shop for tests.\n")
    write(repo, "src/shop/__init__.py", "")
    write(repo, "src/shop/cart.py", CART_V1)
    ids["start"] = commit(repo, "Start the shop: a cart", ADA, "2026-01-05T10:00:00+00:00")

    write(repo, "src/shop/pricing.py", PRICING_V1)
    write(
        repo, "tests/test_cart.py", "from shop.cart import Cart\n\n\ndef test_empty():\n    assert Cart().items == []\n"
    )
    ids["pricing"] = commit(repo, "Add pricing", GRACE, "2026-01-12T10:00:00+00:00")
    git(repo, "tag", "-a", "v0.1", "-m", "First release", date="2026-01-12T11:00:00+00:00")

    write(repo, "config/settings.yml", "currency: EUR\nlocale: en\n")
    write(repo, "config/legacy.ini", "[old]\nmode = classic\n")
    write(repo, "secrets/prod.env", "API_KEY=made-up-secret-value\n")
    write(repo, "data/fixtures/carts.json", '{"carts": []}\n')
    ids["settings"] = commit(repo, "Add settings", ADA, "2026-02-02T10:00:00+00:00")

    git(repo, "checkout", "-q", "-b", "feature/discounts")
    write(repo, "src/shop/pricing.py", PRICING_V2)
    write(repo, "secrets/prod.env", "API_KEY=made-up-secret-value\nDISCOUNT_KEY=made-up-discount-key\n")
    ids["discounts"] = commit(repo, "Add discounts", ALAN, "2026-02-10T10:00:00+00:00")

    git(repo, "checkout", "-q", "main")
    write(repo, "src/shop/cart.py", CART_V2)
    ids["fix"] = commit(repo, "Fix the cart total for empty carts", GRACE, "2026-02-15T10:00:00+00:00")

    git(
        repo,
        "merge",
        "-q",
        "--no-ff",
        "-m",
        "Merge branch 'feature/discounts'",
        "feature/discounts",
        date="2026-02-20T10:00:00+00:00",
    )
    ids["merge"] = git(repo, "rev-parse", "HEAD")
    git(repo, "tag", "v0.2")

    rows = "\n".join(f"{i},product-{i},{100 + i}" for i in range(1, 3001))
    write(repo, "data/products.csv", "id,name,price_cents\n" + rows + "\n")
    write(repo, "assets/logo.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(256)))
    write(repo, "static/app.min.js", "var a=" + "1+" * 2500 + "1;\n")
    (repo / "docs").mkdir()
    os.symlink("../README.md", repo / "docs/latest.md")
    (repo / "config/legacy.ini").unlink()
    ids["catalog"] = commit(
        repo, "Add the catalog and assets; drop the legacy config", ADA, "2026-03-01T10:00:00+00:00"
    )

    # Left uncommitted: the server reads commits only.
    write(repo, "README.md", "# Acme shop\n\nUNCOMMITTED EDIT\n")
    write(repo, "src/shop/draft.py", "DRAFT = True\n")
    return ids
