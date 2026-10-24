"""Shared fixtures: git isolated from the machine's own configuration, and the made-up shop built once."""

import os
from pathlib import Path

import pytest
from mcp import Client
from repos import build_shop

from repo_reader_mcp.config import Config, parse_config
from repo_reader_mcp.server import build_server


@pytest.fixture(scope="session", autouse=True)
def isolated_git():
    """The server's git reads no configuration of the machine running the tests."""
    saved = {k: os.environ.get(k) for k in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM")}
    os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def shop(tmp_path_factory) -> tuple[Path, dict[str, str]]:
    """The made-up shop (read-only for the tests) and its commits by name."""
    path = tmp_path_factory.mktemp("repos") / "shop"
    return path, build_shop(path)


def config_for(path: Path, **settings) -> Config:
    """A configuration serving one repository named `shop`, with any of its settings."""
    limits = settings.pop("limits", None)
    data = {"repositories": [{"name": "shop", "path": str(path), **settings}]}
    if limits:
        data["limits"] = limits
    return parse_config(data, path.parent)


async def ask(config: Config, tool: str, **arguments) -> tuple[str, bool]:
    """One tool's answer through the SDK's own client, in-process: its text, and whether it is an error."""
    async with Client(build_server(config)) as client:
        result = await client.call_tool(tool, arguments)
    return result.content[0].text, result.is_error
