# Changelog

One line per change, newest on top: `YYYY-MM-DD — what was done`.

---

2026-10-24 — repositories' guidance for agents: `AGENTS.md` / `CLAUDE.md` / `.claude/rules` / `.cursor/rules` / skills found on the default branch, text and files from the configuration, `from` another repository, `listed: false`; every answer about a repository says it has guidance (MCP keeps no session), short scoped rules ride with answers about their paths; `read_guidance`; `--check` lists it and warns; a history leaves out commits that changed only what is not served; real Claude Code followed guidance it could not have guessed; milestone 1 done
2026-10-24 — milestone 1's reading: the YAML configuration and its check (`--check`), eight read-only tools over local repositories (`list_repos`, `list_refs`, `read_file`, `list_files`, `log`, `show_commit`, `diff`, `blame`), include / exclude, every git output capped; 108 tests on made-up repositories, every protection failing its test when removed; a refuting review (blame's ignore-revs file closed); real Claude Code answering over stdio; the guide's tools, configuration, safety and getting-started pages; remote repositories now milestone 2, groups planned
2026-10-24 — ready to start: the guide's rule with a test (every tool in `docs/reference/tools.md`), `/close` checks the guide; the site moved to milestone 2; the hosting (pipelab) and where a company's requirements come from written in `CLAUDE.md`; context and parallel-work rules
2026-10-24 — `docs/` is the public documentation's source (a site to come, Astro + Starlight like detectkit's, hosted through pipelab); design, plan, decisions, research moved to `dev/`
2026-10-24 — groundwork: the repository, README, design, plan, decisions, research, the session flow; a skeleton server (stdio, `about`) with tests, ruff and CI
