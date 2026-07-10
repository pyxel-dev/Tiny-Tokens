# Contributing

## Setup

No install step beyond Python 3.9+ — tito is stdlib-only.

```
git clone <repo>
cd tito
scripts/test.sh
```

`scripts/` holds small dev helpers: `scripts/test.sh` runs the suite
(below), `scripts/update.sh` re-runs `tito.py install` so a local edit to
`tito.py` is redeployed to `~/.local/bin/tito` and picked up by your own
Claude Code hook, and `scripts/commit.sh` wraps `cz commit` (see "Commit
messages" below).

## Design principles

These are load-bearing — PRs that violate them will get pushback:

- **tito can never break a command.** Any exception in a filter's `transform`/`render`, any unrecognized output shape, any missing extension — all of it falls back to raw output and the real exit code. Never let a filter bug surface as a crash or a hidden result.
- **Doubt favors passthrough.** In the hook rewriter especially: if parsing a shell command is ambiguous, don't rewrite it. A missed optimization costs nothing; a wrong rewrite changes behavior.
- **Prefer machine-readable formats over parsing human output.** `--porcelain`, `--format=`, `-1F`, `--json`, etc. are more robust across tool versions and locales than scraping default CLI output.
- **stdlib only, single file.** This is a deliberate constraint, not an oversight. Don't add a dependency or split `tito.py` into a package without discussing it first.
- **Exit codes are sacred.** Whatever the wrapped command would have returned, tito returns. Never swallow or remap it.

## Commit messages

Commits follow Conventional Commits with a required scope:
`<type>(<scope>): <description>`, e.g. `feat(extensions): add git`.

Scopes are enforced via [commitizen](https://commitizen-tools.github.io/commitizen/)
(`[tool.commitizen]` in `pyproject.toml`, `cz_customize` provider):

| Scope | Covers |
|---|---|
| `core` | `tito.py` itself — dispatch, registry, hook rewriter, stats, install |
| `extensions` | bundled or user filters (`extensions/`) |
| `docs` | `docs/`, `README.md`, `CONTRIBUTING.md`, `CLAUDE.md` |
| `tests` | `tests/` |
| `*` (other) | anything else — pick "other" and type a custom scope |

Install commitizen (`brew install commitizen`), then run `scripts/commit.sh`
(or `cz commit` / `cz c` directly) instead of `git commit` — it walks
through type, scope, and description and produces a correctly formatted
message. `cz check --message "..."` validates a message without
committing (useful in a pre-commit hook or CI).

## Tests

`unittest`, one file per concern. Current layout (still growing — treat
gaps as where new files should land, not as missing work to backfill
blindly):

| File | Covers |
|---|---|
| `test_output.py` | `_say`/`_paint` |
| `test_settings.py` | `load_settings`, `register_hook` |
| `test_install.py` | `cmd_install`, `should_copy` |
| `test_main.py` | top-level dispatch |
| `extensions/git/test_git.py` | the bundled `git` extension — loads `extensions/git/default.py` directly via `importlib`, exercises `filter()`/`transform()`, then confirms the registry picks it up |

Run everything:

```
scripts/test.sh
```

(equivalent to `python3 -m unittest discover -s tests -v`, run from the
repo root).

When you add a filter or change its output shape, add a golden test: raw fixture in → expected compact string out, following the pattern in `tests/extensions/git/test_git.py`. These tests are the executable spec of what "compact" means for each command.

## Adding an extension

There's no separate "core filter" registration step — every filter, bundled or user-written, is just a file with `COMMANDS` (+ `filter`, optionally `transform`/`SUBCOMMANDS`) that `load_registry()` picks up, from [`extensions/`](../extensions/) (bundled) or `~/.config/tito/filters/` (user). See [Writing Filters](Writing-Filters.md) and [Extensions](Extensions.md) for the contract, and `extensions/git/default.py` for a real example with both `filter` and `transform`.

To add an official one: create `extensions/<name>/default.py` (check `code != 0` → `None` first, same as every existing filter), add a matching golden test under `tests/extensions/<name>/` following the git example above, and run `python3 -m unittest discover -s tests -v` before committing.

If the command's subcommands need genuinely different render logic (not just different flags), use one file per subcommand in that folder instead of a single `default.py` — see "Optional: split one command across subcommands" in [Writing Filters](Writing-Filters.md#optional-split-one-command-across-subcommands). Prefer a stable machine-readable output flag over parsing default text when one exists (see Design principles above); when it doesn't, a long-documented default text shape is acceptable but verify it against a real install of the tool first — an unverified regex against a fast-moving output format (e.g. `next build`'s route table) is worse than leaving the command unhandled.

See [Architecture](Architecture.md) for how this plugs into the dispatch pipeline, and the repo-root `CLAUDE.md` for line-level detail.
