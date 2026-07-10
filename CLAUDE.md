# tito — internals for future development

tito (**Ti**ny **To**kens) is a single-file (`tito.py`, stdlib only) command
wrapper for Claude Code. Golden rule: **it can never break a command.**
Recognized commands get compact output; everything else, and anything that
goes wrong, falls back to the raw output with the real exit code untouched.

User-facing docs (install, writing filters, contributing) live in
[docs/](docs/Home.md) as a GitHub wiki. This file is the internals map —
read it before touching `tito.py`.

## Current scope

tito now has its full pipeline: dispatch, the extension/filter registry,
the hook rewriter, stats, and all meta commands (`gain`, `filters`,
`enable`, `browse`, `disable`, `new-filter`, `hook`, `rewrite`, `install`
— see `USAGE` and the `meta` dict in `main()`). Only one filter ships
today: `extensions/git/default.py`, the reference/example extension —
everything else the docs describe (cargo, npm, docker, per-language
toolchains…) is roadmap, not yet in `extensions/`.

## Output helpers (`_say` / `_paint`)

All user-facing messages go through `_say(emoji, color, msg, stream)`,
which prints an emoji-prefixed, color-coded line. `_paint` strips the ANSI
color when the target stream isn't a TTY, so piped/captured output stays
clean. Colors live in module-level constants (`_RED`, `_GREEN`, `_YELLOW`,
`_CYAN`, `_RESET`). When adding output, use `_say` rather than raw `print`
so the styling and TTY behavior stay consistent. (`cmd_install` is the only
caller today; `cmd_gain`, `cmd_enable`, etc. still use raw `print`.)

## Config / paths

- `config_dir()` — `~/.config/tito`, overridable via `TITO_HOME`.
- `filters_dir()` — `<config_dir>/filters`, where user/downloaded
  extensions live.
- `bundled_extensions_dir()` — `./extensions` next to `tito.py`. Only
  present for repo checkouts; an installed binary has no bundled dir, so
  extensions there only come from `tito enable`/`tito browse`.
- `stats_file()` — `<config_dir>/stats.jsonl`.

## Filter / registry (`Filter`, `load_registry`, `_resolve`, `_router`)

A `Filter` bundles `commands` (list of command names), `render(argv,
stdout, stderr, code) -> str | None`, optional `transform(argv) -> argv`,
a `source` label, and an optional `subcommands` set restricting it to
specific first non-flag args (lets e.g. `go/build.py` and `go/test.py`
split one command across files).

`load_registry()` builds `{command -> Filter}` by walking
`bundled_extensions_dir()` then `filters_dir()` (`load_extensions()`), so a
user copy always overrides the bundled one — later load wins. Each `*.py`
file must define `COMMANDS` (and `filter`, optionally `transform` /
`SUBCOMMANDS`); a broken file is skipped with a stderr warning, never
takes tito down (`load_extensions`'s `try/except`).

When multiple filters claim the same command, `_resolve()` picks a single
`Filter`: no subcommand-restricted filter among them → last loaded wins
(plain override). Otherwise `_router()` builds a routing `Filter` that
dispatches by `_argv_subcommand(argv)` — a subcommand-specific filter wins
for its subcommand, the one filter with no `subcommands` (if any) is the
default for everything unmatched, and with no default an unmatched
subcommand just passes through (`render` returns `None`).

## Dispatch (`dispatch`)

1. Look up the `Filter` for `argv[0]` in the registry; no filter → run
   the command as-is via `subprocess.run(argv)` (no capture), preserving
   its exit code; `FileNotFoundError` → print `tito: <cmd>: command not
   found`, exit 127.
2. Filter found → run its `transform(argv)` if present (any exception
   falls back to the untransformed argv).
3. `run()` executes the (possibly transformed) argv, capturing
   stdout/stderr/exit code.
4. `flt.render(argv, stdout, stderr, code)` — any exception is treated as
   `None`.
5. `None` → write the raw stdout/stderr straight through, return the real
   code. A string → `record_stats()`, write the compact string (newline
   appended if missing) to stdout; on non-zero exit also write the raw
   stderr (so Claude still sees the real error) — see `filter`
   conventions in `extensions/git/default.py` (check `code != 0` first).

Every step after "filter found" is wrapped so an exception degrades to
raw output rather than crashing or hiding the command's result — that's
the golden rule made concrete.

## Stats (`record_stats`, `cmd_gain`)

Every filtered (non-`None`) dispatch appends one JSONL line — `ts`, `cmd`,
`raw` (raw byte length), `filtered` (compact byte length) — to
`stats_file()`; write failures are swallowed (`except OSError: pass`),
bookkeeping must never fail a command.

`tito gain` aggregates the file per command and overall: count, tokens
estimated as `bytes // 4`, percent saved, and a rough time-saved estimate
(`tokens / 50`, shown only under 24h of estimated savings — past that the
number is too coarse to be meaningful). Rows are colored green/red
relative to the average when `_gain_color_enabled()` (TTY and no
`NO_COLOR`). `tito gain --reset` deletes the stats file.

## Extensions registry (`enable`/`disable`/`browse`/`new-filter`/`filters`)

- `registry_url()` — `TITO_REGISTRY` env override, else `REGISTRY_URL`
  (`github.com/pyxel-dev/Tiny-Tokens` raw URL).
- `_filter_rel_path(name)` / `_filter_path(name)` — map a user-facing name
  to `<filters_dir>/<name>/default.py` (bare name) or `<name>.py` (already
  contains `/`, e.g. `go/build`); `_filter_path` rejects path traversal
  (anything that normalizes outside `filters_dir()`).
- `tito enable <name>` (`cmd_enable`/`_do_enable`) — if
  `<path>.disabled` exists locally, restores it (no re-download, so local
  edits survive a disable/enable cycle); otherwise fetches
  `<name>/default.py` from the registry.
- `tito disable <name>` — renames the installed file to `<path>.disabled`
  (kept on disk, not deleted).
- `tito browse` (`cmd_browse`/`_fetch_manifest`/`_browse_ui`) — requires a
  TTY; fetches `manifest.json` from the registry, shows a curses
  checkbox picker (↑/↓ or j/k, space to toggle, a/n select-all/none,
  Enter to install checked, q/Esc to cancel), then `_do_enable`s each
  selection.
- `tito new-filter <name>` — writes `FILTER_SKELETON` to
  `<filters_dir>/<name>/default.py` (or `<name>.py` if nested), refuses
  to overwrite an existing file.
- `tito filters` (`cmd_filters`) — lists bundled and user filters found by
  walking both directories; strips the `.py`/`.py.disabled` suffix and a
  trailing `/default`, tags disabled ones.

## Hook rewriter (`rewrite_command`, `_split_segments`, `cmd_hook`, `cmd_rewrite`)

`_split_segments(cmd)` splits a shell command on `&&`/`||`/`;` outside
quotes, tracking single/double quotes and backslash-escapes. Returns
`None` (refuse to touch anything) on: unbalanced quotes, command
substitution (`` ` `` or `$(`), redirection (`<`/`>`), a pipe (`|` —
downstream consumes raw output, so filtering here would be wrong), or
backgrounding (`&`). `_rewrite_segment` prefixes a segment's first word
with `tito ` only if that word is in the handled-commands set, isn't
already `tito`/`rtk`, and isn't a `VAR=value` assignment.
`rewrite_command(cmd, handled)` composes both: doubt always favors **no
rewrite** — a missed rewrite costs one unfiltered turn, a wrong rewrite
could change what a pipeline actually does.

`cmd_hook` is the registered `PreToolUse` hook body (`tito hook`, reading
JSON on stdin): loads the registry to get the handled-commands set,
rewrites `tool_input.command`, and if changed, emits the
`hookSpecificOutput.updatedInput` JSON Claude Code expects. Wrapped in a
bare `try/except: pass` — never crash, never block; any problem means no
output, exit 0, original command runs untouched.

`tito rewrite <cmd>...` (or piped via stdin) prints the rewritten form
without executing anything — for debugging the rewrite logic. Same
never-fail contract: on any error it echoes the input unchanged.

## Install (`cmd_install`)

Order matters and is deliberate:

1. Validate `~/.claude/settings.json` is parseable **before** touching any
   file — a corrupt settings file must fail loudly with nothing copied, not
   half-install.
2. Copy the binary to `~/.local/bin/tito` (skipped via `should_copy()` if
   already running from that exact path, avoiding `shutil.SameFileError` on
   `tito install` re-runs).
3. Warn (don't fail) if `~/.local/bin` isn't on `PATH`.
4. Register the `PreToolUse` hook idempotently (`register_hook()` scans for
   an existing `tito` hook command before appending).

The registered hook command is `~/.local/bin/tito hook` — and `hook` is
now implemented (see above), so a fresh `tito install` produces a live
hook, not an inert one.

`load_settings(path)` returns `{}` when the file is missing, `None` when
it's unreadable — the `None` sentinel is what `cmd_install` keys on to
refuse to proceed.

## Locations

- Binary: `~/.local/bin/tito`
- Claude Code settings: `~/.claude/settings.json`
- Config dir: `~/.config/tito` (filters under `filters/`, stats at
  `stats.jsonl`), overridable via `TITO_HOME`.

## Tests

`tests/` currently covers output helpers (`test_output.py`), settings
load/hook registration (`test_settings.py`), install (`test_install.py`),
top-level dispatch (`test_main.py`), and the bundled git extension
(`tests/extensions/git/test_git.py`) — one file per concern, mirrored
against `extensions/` for per-extension golden tests. `CONTRIBUTING.md`'s
test-layout table describes a larger target structure (`core/`,
`filters/`, `hook/`, `registry/`, `meta/`) that tests haven't grown into
yet; treat it as where new test files should land, not as what exists
today.

## Design constraints

- **Stdlib only, single file.** Stated design constraint, not an oversight
  — don't introduce a dependency or split `tito.py` into a package without
  discussing it first.
- **The golden rule.** When extending, wrap anything that can fail so an
  exception degrades to the raw path rather than crashing or hiding output.
- **Doubt favors passthrough**, especially in the hook rewriter — a missed
  optimization costs nothing, a wrong rewrite changes behavior.
