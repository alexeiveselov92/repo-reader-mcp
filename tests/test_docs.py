"""The guide names every tool, and the site carries every page of the guide: a tool without its entry in
docs/reference/tools.md, or a page of docs/ the site's build doesn't list, fails here."""

import pathlib
import re

import pytest
from mcp import Client

from repo_reader_mcp.server import build_server

pytestmark = pytest.mark.anyio

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS_PAGE = ROOT / "docs" / "reference" / "tools.md"


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_every_tool_has_its_entry_in_the_guide():
    async with Client(build_server()) as client:
        names = [tool.name for tool in (await client.list_tools()).tools]
    page = TOOLS_PAGE.read_text(encoding="utf-8")
    missing = [name for name in names if f"## `{name}`" not in page]
    assert not missing, f"tools without an entry in docs/reference/tools.md: {missing}"


def test_the_site_carries_every_page_of_the_guide():
    listed = set(re.findall(r"src: '(docs/[^']+\.md)'", (ROOT / "website" / "scripts" / "sync-docs.mjs").read_text()))
    pages = {str(page.relative_to(ROOT)) for page in (ROOT / "docs").rglob("*.md")}
    assert pages == listed, f"pages of docs/ missing from the site: {sorted(pages - listed)}"
