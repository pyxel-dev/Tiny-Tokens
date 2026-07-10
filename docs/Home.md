# tito wiki

tito is a tiny, single-file command wrapper that saves tokens in [Claude Code](https://claude.com/claude-code). Recognized commands (git, grep, find, diff, env, ls…) get compact, machine-friendly output; everything else passes through untouched. Exit codes are always preserved, and any filter problem falls back to the raw output — tito can never break a command.

## Pages

- **[Architecture](Architecture.md)** — how the dispatch pipeline and the Claude Code hook fit together.
- **[Writing Filters](Writing-Filters.md)** — add support for a new command, locally.
- **[Extensions](Extensions.md)** — the official extension registry, `enable`/`disable`, priority rules.
- **[Contributing](../CONTRIBUTING.md)** — dev setup, tests, design principles for PRs.

For AI agents (Claude Code sessions) working on tito itself, see the repo-root [CLAUDE.md](../CLAUDE.md) — it's a denser internals map keyed to function names and line numbers, meant to be read before editing `tito.py`.

## Quick links

- Install: `python3 tito.py install`
- Stats: `tito gain`
- List active filters: `tito filters`
- Source: [pyxel-dev/Tiny-Tokens](https://github.com/pyxel-dev/Tiny-Tokens)
