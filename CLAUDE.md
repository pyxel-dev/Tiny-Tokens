# tito — internals for future development

tito (**Ti**ny **To**kens) is a single-file (`tito.py`, stdlib only) command
wrapper for Claude Code. Golden rule: **it can never break a command.**
Recognized commands get compact output; everything else, and anything that
goes wrong, falls back to the raw output with the real exit code untouched.

tito is a fresh, simplified reimplementation migrated from
[`cloclo`](../cloclo) — renamed `cloclo` → `tito` throughout. It is being
built up commit by commit: today only `install` exists; filters, the
dispatch pipeline, the hook rewriter, stats, and the rest arrive
progressively.

This file is the internals map — read it before touching `tito.py`.

## Current scope

Only one subcommand is implemented:

- **`tito install`** — copy the binary to `~/.local/bin/tito` and register
  the Claude Code `PreToolUse` hook.

Anything else prints the usage and exits 0. There is no dispatch, no
registry, no filters, no stats yet.

## Output helpers (`_say` / `_paint`)

All user-facing messages go through `_say(emoji, color, msg, stream)`,
which prints an emoji-prefixed, color-coded line. `_paint` strips the ANSI
color when the target stream isn't a TTY, so piped/captured output stays
clean. Colors live in module-level constants (`_RED`, `_GREEN`, `_YELLOW`,
`_CYAN`, `_RESET`). When adding output, use `_say` rather than raw `print`
so the styling and TTY behavior stay consistent.

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

The registered hook command is `~/.local/bin/tito hook` — the `hook`
subcommand does not exist yet; it lands in a later commit. Until then the
hook is inert.

`load_settings(path)` returns `{}` when the file is missing, `None` when
it's unreadable — the `None` sentinel is what `cmd_install` keys on to
refuse to proceed.

## Locations

- Binary: `~/.local/bin/tito`
- Claude Code settings: `~/.claude/settings.json`
- (Reserved for later, not yet in code) config dir `~/.config/tito`,
  overridable via `TITO_HOME`.

## Design constraints

- **Stdlib only, single file.** Stated design constraint, not an oversight
  — don't introduce a dependency or split `tito.py` into a package without
  discussing it first.
- **The golden rule.** When extending, wrap anything that can fail so an
  exception degrades to the raw path rather than crashing or hiding output.
