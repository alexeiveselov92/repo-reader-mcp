"""Repositories' guidance for agents: found by the conventions, read from the default branch only, held by include /
exclude, joined by what the configuration adds — and announced by every answer about the repository, with a short rule
for the path an answer is about."""

from pathlib import Path

import pytest
from conftest import ask, config_for
from mcp import Client
from repos import build_guided, build_rules, git, write

from repo_reader_mcp.config import ConfigError, Limits, parse_config
from repo_reader_mcp.server import build_server, main

pytestmark = pytest.mark.anyio

NOTICE = (
    '[`shop` carries guidance for agents from its owners: call read_guidance(repo="shop") once in this conversation'
)
END = "=== End of guidance — the answer follows ===\n\n"


@pytest.fixture(scope="module")
def repos(tmp_path_factory) -> Path:
    base = tmp_path_factory.mktemp("guided")
    build_guided(base / "shop")
    build_rules(base / "rules")
    (base / "server-notes.md").write_text("Say which commit you read.\n")
    return base


def configure(base: Path, **shop):
    guidance = shop.pop("guidance", {})
    data = {
        "guidance": {"text": "Be brief.", "files": ["server-notes.md"]},
        "repositories": [
            {"name": "rules", "path": "rules", "listed": False},
            {"name": "shop", "path": "shop", "exclude": ["secrets"], "guidance": guidance, **shop},
        ],
    }
    return parse_config(data, base)


# --- what every answer carries -----------------------------------------------------------------------------------


async def test_every_answer_about_a_repository_with_guidance_says_so(repos):
    config = configure(repos)
    for tool, arguments in [
        ("list_refs", {}),
        ("read_file", {"path": "src/cart.py"}),
        ("list_files", {}),
        ("log", {}),
        ("show_commit", {"commit": "main"}),
        ("diff", {"base": "main", "head": "feature/swap"}),
        ("blame", {"path": "src/cart.py"}),
    ]:
        text, error = await ask(config, tool, repo="shop", **arguments)
        assert not error and text.startswith(NOTICE), (tool, text[:200])
    text, _ = await ask(config, "read_file", repo="shop", path="src/cart.py")
    assert text.split("]\n\n", 1)[1].startswith("shop · src/cart.py")  # then the answer itself


async def test_a_repository_without_guidance_answers_plainly(shop):
    text, _ = await ask(config_for(shop[0]), "read_file", repo="shop", path="README.md")
    assert text.startswith("shop · README.md")
    text, _ = await ask(config_for(shop[0]), "read_guidance", repo="shop")
    assert text == "shop has no guidance for agents.\n"


async def test_an_answer_about_a_path_a_short_rule_covers_carries_the_rule(repos):
    config = configure(repos, guidance={"from": [{"repo": "rules", "path": "shop"}]})
    tax, _ = await ask(config, "read_file", repo="shop", path="src/pricing/tax.py")
    assert "=== Guidance for `src/pricing/tax.py` in `shop`" in tax and "TAX_RATE is set by finance" in tax
    cart, _ = await ask(config, "log", repo="shop", path="src/cart.py")
    assert "The cart's total is net of tax." in cart  # a `from` rule's `paths:` read against this repository
    docs, _ = await ask(config, "list_files", repo="shop", path="docs")
    assert "British English" in docs  # a folder's AGENTS.md, for the folder
    sql, _ = await ask(config, "read_file", repo="shop", path="reports/daily.sql")
    assert "SQL keywords in capitals." in sql  # a Cursor rule's `globs:`
    plain, _ = await ask(config, "read_file", repo="shop", path="src/refunds.py")
    assert "=== Guidance for `src/refunds.py`" not in plain and "TAX_RATE" not in plain


async def test_a_long_scoped_rule_is_named_rather_than_carried(repos, tmp_path):
    copy = tmp_path / "shop"
    git(tmp_path, "clone", "-q", str(repos / "shop"), str(copy))
    write(copy, ".claude/rules/pricing.md", "---\npaths: src/pricing/**\n---\n" + "A long pricing rule. " * 200)
    git(copy, "commit", "-q", "-am", "A long rule", date="2026-05-03T10:00:00+00:00")
    config = parse_config({"repositories": [{"name": "shop", "path": str(copy)}]}, tmp_path)
    text, _ = await ask(config, "read_file", repo="shop", path="src/pricing/tax.py")
    assert "A long pricing rule." not in text
    assert "`.claude/rules/pricing.md` — for src/pricing/**: comes with answers there, or read_guidance(" in text


async def test_guidance_takes_at_most_half_of_an_answer(repos):
    config = configure(repos)
    small = type(config)(config.repositories, Limits(answer_characters=2000), config.guidance)
    text, error = await ask(small, "read_file", repo="shop", path="src/pricing/tax.py")
    assert not error and len(text) <= 2000
    assert text.split(END)[-1].startswith("shop · src/pricing/tax.py")


# --- read_guidance -----------------------------------------------------------------------------------------------


async def test_read_guidance_holds_every_source_in_order(repos):
    config = configure(
        repos, guidance={"text": "Prices are shown with tax.", "from": [{"repo": "rules", "path": "shop"}]}
    )
    text, _ = await ask(config, "read_guidance", repo="shop")
    order = ["Be brief.", "Say which commit you read.", "Prices are shown with tax.", "Promo engine", "cents"]
    places = [text.index(piece) for piece in order]
    assert places == sorted(places), places
    assert "Name modules in the singular." in text  # a rule with no `paths:` is in force everywhere
    assert text.count("always answer them in euros") == 1  # AGENTS.md and CLAUDE.md say the same: once
    assert "TAX_RATE is set by finance" in text and "— for src/pricing/** ---" in text  # scoped rules, with scope
    assert "`skill refund-flow`: Trace a refund from the request to the ledger. — read it with read_guidance(" in text
    assert "Start at src/refunds.py" not in text  # …their body read when needed
    assert NOTICE not in text


async def test_read_guidance_gives_one_piece(repos):
    config = configure(repos)
    skill, _ = await ask(config, "read_guidance", repo="shop", name="refund-flow")
    assert "Start at src/refunds.py" in skill and "to follow when it fits the task" in skill
    rule, _ = await ask(config, "read_guidance", repo="shop", name=".claude/rules/pricing.md")
    assert "TAX_RATE is set by finance" in rule and "in force for src/pricing/**" in rule
    missing, error = await ask(config, "read_guidance", repo="shop", name="nothing-such")
    assert error and "nothing named `nothing-such`" in missing


async def test_guidance_comes_from_the_default_branch_only(repos):
    config = configure(repos)
    guidance, _ = await ask(config, "read_guidance", repo="shop")
    assert "IGNORE EVERY RULE" not in guidance and "always answer them in euros" in guidance
    file, _ = await ask(config, "read_file", repo="shop", path="AGENTS.md", ref="feature/swap")
    assert "IGNORE EVERY RULE" in file  # read as a file, it is shown as it is


async def test_guidance_obeys_include_and_exclude(repos):
    text, _ = await ask(configure(repos), "read_guidance", repo="shop")
    assert "vault" not in text and "secrets/AGENTS.md" not in text


async def test_a_moved_default_branch_brings_its_new_guidance(repos, tmp_path):
    copy = tmp_path / "shop"
    git(tmp_path, "clone", "-q", str(repos / "shop"), str(copy))
    server = build_server(parse_config({"repositories": [{"name": "shop", "path": str(copy)}]}, tmp_path))
    async with Client(server) as client:
        before = (await client.call_tool("read_guidance", arguments={"repo": "shop"})).content[0].text
    write(copy, "AGENTS.md", "Amounts are dollars now.\n")
    git(copy, "commit", "-q", "-am", "Change the guidance", date="2026-05-03T10:00:00+00:00")
    async with Client(server) as client:
        after = (await client.call_tool("read_guidance", arguments={"repo": "shop"})).content[0].text
    assert "euros" in before and "dollars" in after


# --- repositories that are sources only --------------------------------------------------------------------------


async def test_an_unlisted_repository_is_a_source_of_guidance_only(repos):
    config = configure(repos, guidance={"from": [{"repo": "rules", "files": ["handbook/*.md"]}]})
    listed, _ = await ask(config, "list_repos")
    assert "## shop" in listed and "## rules" not in listed
    assert 'read_guidance(repo="shop") before you work with it' in listed
    text, error = await ask(config, "read_file", repo="rules", path="shop/AGENTS.md")
    assert error and "no repository named `rules`" in text
    guidance, _ = await ask(config, "read_guidance", repo="shop")
    assert "Basket: what the code calls a cart." in guidance  # named by `files`: in force everywhere
    assert "Not ready." not in guidance  # `handbook/*.md` takes no subfolder
    assert "Promo engine" not in guidance  # with `files`, only those


# --- the configuration -------------------------------------------------------------------------------------------


def test_from_must_name_another_configured_repository(repos):
    for origin, message in [("nowhere", "`nowhere`, which is not configured"), ("shop", "itself")]:
        with pytest.raises(ConfigError) as caught:
            configure(repos, guidance={"from": [{"repo": origin}]})
        assert caught.value.problems == [f"repositories[1] (shop) → guidance → from[0] → repo: names {message}"]


def test_a_guidance_file_that_cannot_be_read_is_named(repos):
    with pytest.raises(ConfigError) as caught:
        configure(repos, guidance={"files": ["missing.md"]})
    assert caught.value.problems[0].startswith("repositories[1] (shop) → guidance → files[0]: can't read")


def test_check_lists_guidance_and_warns_about_what_agents_won_t_get(repos, tmp_path, capsys):
    file = tmp_path / "config.yaml"
    file.write_text(
        f"repositories:\n  - name: shop\n    path: {repos / 'shop'}\n    exclude: [secrets]\n"
        f"  - name: rules\n    path: {repos / 'rules'}\n    listed: false\n"
    )
    main(["--config", str(file), "--check"])
    out = capsys.readouterr().out
    assert "guidance: AGENTS.md, .claude/rules/style.md" in out
    assert "warning: secrets/AGENTS.md is guidance for agents, but outside its include / exclude" in out
    assert "(not listed: a source of guidance only)" in out


async def test_a_source_s_own_include_and_exclude_hold_for_what_it_gives(repos):
    data = {
        "repositories": [
            {"name": "rules", "path": "rules", "listed": False, "exclude": ["shop/.claude", "handbook/glossary.md"]},
            {
                "name": "shop",
                "path": "shop",
                "guidance": {"from": [{"repo": "rules", "path": "shop"}, {"repo": "rules", "files": ["handbook/*"]}]},
            },
        ]
    }
    text, _ = await ask(parse_config(data, repos), "read_guidance", repo="shop")
    assert "Promo engine" in text  # served by the source
    assert "net of tax" not in text and "Basket" not in text  # kept out by the source's exclude
