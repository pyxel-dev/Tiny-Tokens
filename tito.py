#!/usr/bin/env python3
"""tito - token-saving command wrapper for Claude Code.

Recognized commands get compact, filtered output; anything else passes
through untouched. Exit codes are always preserved. Golden rule: tito
can never break a command.

This file is pure infrastructure: a dispatch pipeline, an extension
system, a PreToolUse hook that rewrites handled commands into
`tito <cmd>`, and the install/gain meta commands. Every command's filter
logic lives in an extension — bundled ones under ./extensions (next to
this script) and user ones under ~/.config/tito/filters — so a user copy
always overrides the bundled one.
"""

import curses
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

# --- Menu -----------------------------------------------------------------

USAGE = """usage: tito <command> [args...]   run a command with filtered output
       tito gain                  show token savings stats
       tito gain --reset          wipe recorded savings stats
       tito filters               list loaded filters
       tito enable <name>         download and enable an official extension
       tito browse                browse the registry and install extensions via checkbox
       tito disable <name>        disable an extension
       tito new-filter <name>     generate a custom filter skeleton
       tito hook                  PreToolUse-style hook (reads JSON on stdin); Claude Code
       tito rewrite <cmd>...      print the tito-prefixed rewrite of a command (or unchanged)
       tito install               install binary and configure the Claude Code hook
"""


# --- Custom print helpers -------------------------------------------------

# ANSI colors for terminal output. _paint strips them when the target stream
# isn't a TTY, so piped or captured output stays clean.
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_RESET = "\033[0m"


def _paint(color, text, stream):
    """Wrap text in ANSI color, but only when stream is a TTY."""
    if stream.isatty():
        return f"{color}{text}{_RESET}"
    return text


def _say(emoji, color, msg, stream=sys.stdout):
    """Print an emoji-prefixed, color-coded message to stream."""
    print(f"{emoji} {_paint(color, msg, stream)}", file=stream)


# --- config / paths -------------------------------------------------------

def config_dir():
    return os.path.expanduser(os.environ.get("TITO_HOME", "~/.config/tito"))


def filters_dir():
    return os.path.join(config_dir(), "filters")


def bundled_extensions_dir():
    """Extensions shipped alongside this script (repo checkouts).

    Loaded before the user filters dir so a user copy in
    ~/.config/tito/filters overrides the bundled one. Absent for an
    installed binary — there, extensions come from `tito enable`.
    """
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "extensions")


def stats_file():
    return os.path.join(config_dir(), "stats.jsonl")


# --- run helper -----------------------------------------------------------

def run(argv):
    """Run argv capturing output. Returns (stdout, stderr, exit_code)."""
    proc = subprocess.run(argv, capture_output=True, text=True, errors="replace")
    return proc.stdout, proc.stderr, proc.returncode


# --- Filter ---------------------------------------------------------------

class Filter:
    """A command filter. render(argv, stdout, stderr, code) -> str | None.

    Returning None keeps the raw output. transform(argv) -> argv may
    rewrite the command before execution (e.g. add --porcelain).
    `subcommands` (optional set) restricts the filter to specific first
    non-flag args — lets `go/build.py` and `go/test.py` split one command
    (`go`) across files. None means "any subcommand".
    """

    def __init__(self, commands, render, transform=None, source="core", subcommands=None):
        self.commands = list(commands)
        self.render = render
        self.transform = transform
        self.source = source
        self.subcommands = set(subcommands) if subcommands else None


# --- registry -------------------------------------------------------------

def _argv_subcommand(argv):
    """First non-flag argument after the command, or None."""
    for arg in argv[1:]:
        if not arg.startswith("-"):
            return arg
    return None


def _iter_filter_files(directory):
    """Recursively yield sorted *.py paths under directory.

    Skips __pycache__ and dot-dirs. .py.disabled files don't end in .py,
    so they're naturally excluded (kept on disk for `disable`/re-enable).
    """
    out = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for fn in files:
            if fn == "__init__.py":
                continue
            if fn.endswith(".py"):
                out.append(os.path.join(root, fn))
    return sorted(out)


def _load_filter_module(path):
    """Load a filter file as a module, returning the module object."""
    name = "tito_ext_" + os.path.basename(path)[:-3]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_extensions(by_command, directory):
    """Load <directory>/**/*.py filters, appending to by_command.

    by_command maps command name -> list[Filter] in load order; called
    once for bundled extensions and once for the user filters dir, so a
    user's copy overrides the bundled one. A file may declare
    SUBCOMMANDS to restrict which subcommand it handles (e.g.
    go/build.py handles only `go build`). A broken file is skipped with
    a warning — it must never take tito down.
    """
    if not os.path.isdir(directory):
        return
    for path in _iter_filter_files(directory):
        rel = os.path.relpath(path, directory)
        try:
            mod = _load_filter_module(path)
            flt = Filter(
                list(mod.COMMANDS),
                mod.filter,
                getattr(mod, "transform", None),
                source=rel,
                subcommands=getattr(mod, "SUBCOMMANDS", None),
            )
        except Exception as exc:
            print(f"tito: skipping broken filter {rel}: {exc}", file=sys.stderr)
            continue
        for cmd in flt.commands:
            by_command.setdefault(cmd, []).append(flt)


def _resolve(filters):
    """Pick one Filter for a command from its loaded filters.

    Load order is bundled first, then user. No subcommand filters ->
    last writer wins (user overrides bundled). Any subcommand filter ->
    build a routing Filter.
    """
    if not any(f.subcommands for f in filters):
        return filters[-1]
    return _router(filters)


def _router(filters):
    """Combine filters for one command into one that routes by subcommand.

    A subcommand-specific filter wins for its subcommand; the last
    no-subcommand (default) filter handles anything unmatched; with no
    default, unmatched subcommands pass through (render returns None).
    """
    default = None
    by_sub = {}
    for f in filters:  # bundled, then user in load order
        if f.subcommands:
            for s in f.subcommands:
                by_sub[s] = f
        else:
            default = f
    commands = sorted({c for f in filters for c in f.commands})

    def transform(argv):
        f = by_sub.get(_argv_subcommand(argv), default)
        return f.transform(list(argv)) if (f and f.transform) else list(argv)

    def render(argv, stdout, stderr, code):
        f = by_sub.get(_argv_subcommand(argv), default)
        return f.render(argv, stdout, stderr, code) if f else None

    return Filter(commands, render, transform, source=commands[0] if commands else "?")


def load_registry():
    """Map command name -> Filter.

    Bundled extensions (shipped in ./extensions next to this script) are
    loaded first, then user extensions from ~/.config/tito/filters/, so a
    user copy overrides the bundled one. Subcommand-split extensions
    (e.g. go/build.py + go/test.py) are merged into one routing Filter
    per command.
    """
    by_command = {}
    load_extensions(by_command, bundled_extensions_dir())
    load_extensions(by_command, filters_dir())
    return {cmd: _resolve(filters) for cmd, filters in by_command.items()}


# --- stats ----------------------------------------------------------------

def record_stats(cmd, raw, filtered):
    """Append one JSONL savings record. Never let bookkeeping fail a command."""
    try:
        os.makedirs(config_dir(), exist_ok=True)
        with open(stats_file(), "a") as f:
            f.write(json.dumps(
                {"ts": int(time.time()), "cmd": cmd, "raw": raw, "filtered": filtered}
            ) + "\n")
    except OSError:
        pass


def _gain_color_enabled():
    """True when it's safe to emit ANSI color: a real terminal, and the
    user hasn't opted out via NO_COLOR (https://no-color.org)."""
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def cmd_gain(args):
    """Aggregate and print token savings, or reset stats with --reset."""
    if args and args[0] == "--reset":
        return cmd_gain_reset(args[1:])
    path = stats_file()
    if not os.path.exists(path):
        print("no stats yet")
        return 0
    totals = {}
    with open(path) as f:
        for line in f:
            try:
                rec = json.loads(line)
                key, raw, flt = rec["cmd"], int(rec["raw"]), int(rec["filtered"])
            except (ValueError, KeyError, TypeError):
                continue
            t = totals.setdefault(key, [0, 0, 0])
            t[0] += 1
            t[1] += raw
            t[2] += flt
    if not totals:
        print("no stats yet")
        return 0
    grand_raw = sum(t[1] for t in totals.values())
    grand_flt = sum(t[2] for t in totals.values())
    grand_runs = sum(t[0] for t in totals.values())

    # Tokens are estimated as bytes // 4 (the rule of thumb used across
    # tito). Time saved is linear in tokens saved (~50 tok/s below), so
    # sorting by tokens saved is the same order as sorting by time saved.
    rows = []
    for cmd, (n, raw, flt) in totals.items():
        raw_tok, flt_tok = raw // 4, flt // 4
        saved_tok = raw_tok - flt_tok
        pct = 100 * saved_tok / raw_tok if raw_tok else 0
        rows.append((cmd, n, saved_tok, pct))
    rows.sort(key=lambda r: r[2], reverse=True)
    avg_saved = sum(r[2] for r in rows) / len(rows)

    color = _gain_color_enabled()
    green, red, reset = "\033[32m", "\033[31m", "\033[0m"

    header = f"{'command':<10} {'count':>5}  {'saved':>8}"
    print(header)
    print("-" * len(header))
    for cmd, n, saved_tok, pct in rows:
        line = f"{cmd:<10} {n:>5}  {saved_tok:>8} ({pct:.0f}%)"
        if color:
            c = green if saved_tok >= avg_saved else red
            line = f"{c}{line}{reset}"
        print(line)

    saved_tokens = grand_raw // 4 - grand_flt // 4
    pct = 100 * saved_tokens / (grand_raw // 4) if grand_raw else 0
    print()
    print(f"count: {grand_runs}")
    print(f"input tokens (raw, unfiltered):  ~{grand_raw // 4}")
    print(f"output tokens (filtered, sent):  ~{grand_flt // 4}")
    print(f"total saved: ~{saved_tokens} tokens ({pct:.0f}%)")

    # Rough reading-speed estimate (~50 tok/s), not a measured latency.
    # Past a day the estimate is too coarse to be meaningful, so it's
    # omitted rather than shown as a misleadingly precise number.
    seconds = saved_tokens / 50
    if 0 < seconds < 60:
        print(f"time saved: ~{seconds:.0f}s (rough estimate, ~50 tok/s)")
    elif 60 <= seconds < 3600:
        print(f"time saved: ~{seconds / 60:.1f}min (rough estimate, ~50 tok/s)")
    elif 3600 <= seconds < 86400:
        print(f"time saved: ~{seconds / 3600:.1f}h (rough estimate, ~50 tok/s)")
    return 0


def cmd_gain_reset(args):
    """Delete the stats file, wiping all recorded savings data."""
    path = stats_file()
    if not os.path.exists(path):
        print("no stats yet")
        return 0
    os.remove(path)
    print(f"reset: removed {path}")
    return 0


# --- extensions registry --------------------------------------------------

# Official extensions registry (github.com/Tiny-Tokens/tito). Override
# with the TITO_REGISTRY env var if you publish extensions elsewhere.
REGISTRY_URL = "https://raw.githubusercontent.com/Tiny-Tokens/tito/main/extensions"


def registry_url():
    """TITO_REGISTRY env override if set, else the official REGISTRY_URL."""
    return os.environ.get("TITO_REGISTRY", REGISTRY_URL)


FILTER_SKELETON = '''"""Custom tito filter."""

COMMANDS = ["mycmd"]  # commands this filter intercepts
# SUBCOMMANDS = ["build"]  # optional: only handle this subcommand
                           # (lets you split one command across files,
                           # e.g. extensions/go/build.py + go/test.py)


def filter(argv, stdout, stderr, code):
    """Return the compact output, or None to keep the raw output."""
    if code != 0:
        return None  # let Claude see real errors
    lines = [l for l in stdout.splitlines() if l.strip()]
    return "\\n".join(lines)
'''


def _filter_rel_path(name):
    """Map a user-facing filter name to its relative path under filters_dir().

    Every extension lives in its own folder, one file per name. A bare
    name (no "/") is a single-file extension, e.g. "curl" ->
    "curl/default.py". A name that already contains "/" (e.g.
    "go/build") points at an explicit file inside a multi-file
    ecosystem folder and is used as-is.
    """
    if "/" in name:
        return name + ".py"
    return name + "/default.py"


def _filter_path(name):
    """Resolve a (possibly nested) filter name to a .py path under
    filters_dir(). Returns None (and warns) on path traversal — `name`
    may be `go/build` but never `../x` or absolute.
    """
    base = filters_dir()
    path = os.path.normpath(os.path.join(base, _filter_rel_path(name)))
    if path != base and not path.startswith(base + os.sep):
        print(f"error: invalid filter name {name!r}", file=sys.stderr)
        return None
    return path


def _do_enable(name):
    """Fetch or restore extension `name` into filters_dir().

    Returns (ok, message). message is "" when _filter_path() already
    printed its own error (invalid/traversal name) — callers should
    skip printing an empty message.
    """
    dest = _filter_path(name)
    if dest is None:
        return False, ""
    disabled = dest + ".disabled"
    if os.path.exists(disabled):
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        os.replace(disabled, dest)
        return True, f"enabled {name} (local)"
    url = f"{registry_url()}/{_filter_rel_path(name)}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            code = resp.read().decode("utf-8")
    except Exception as exc:
        return False, f"error: could not fetch {url}: {exc}"
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "w") as f:
        f.write(code)
    return True, f"enabled {name}"


def cmd_enable(args):
    if not args:
        print("usage: tito enable <name>", file=sys.stderr)
        return 1
    ok, msg = _do_enable(args[0])
    if msg:
        print(msg, sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


def cmd_disable(args):
    if not args:
        print("usage: tito disable <name>", file=sys.stderr)
        return 1
    name = args[0]
    src = _filter_path(name)
    if src is None:
        return 1
    if not os.path.exists(src):
        print(f"error: {name} is not installed", file=sys.stderr)
        return 1
    os.replace(src, src + ".disabled")
    print(f"disabled {name}")
    return 0


def _fetch_manifest():
    """Fetch and parse extensions/manifest.json from the registry.

    Returns a list of {"name", "description", "commands"} dicts, or
    None on network/parse failure (prints its own error to stderr).
    """
    url = f"{registry_url()}/manifest.json"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as exc:
        print(f"error: could not fetch {url}: {exc}", file=sys.stderr)
        return None
    try:
        data = json.loads(raw)
        return list(data["extensions"])
    except Exception as exc:
        print(f"error: malformed manifest at {url}: {exc}", file=sys.stderr)
        return None


def _local_status(name):
    """Return "enabled", "disabled", or "" for extension `name`."""
    path = _filter_path(name)
    if path is None:
        return ""
    if os.path.exists(path):
        return "enabled"
    if os.path.exists(path + ".disabled"):
        return "disabled"
    return ""


def _browse_step(state, key, n):
    """Apply one keypress to browse selection state.

    state: {"cursor": int, "selected": set[int]}. Returns (new_state,
    action) where action is None (continue), "confirm", or "cancel".
    """
    cursor, selected = state["cursor"], set(state["selected"])
    action = None
    if key in (curses.KEY_UP, ord("k")):
        cursor = max(0, cursor - 1)
    elif key in (curses.KEY_DOWN, ord("j")):
        cursor = min(n - 1, cursor + 1)
    elif key == ord(" "):
        selected ^= {cursor}
    elif key == ord("a"):
        selected = set(range(n))
    elif key == ord("n"):
        selected = set()
    elif key in (curses.KEY_ENTER, 10, 13):
        action = "confirm"
    elif key in (27, ord("q")):
        action = "cancel"
    return {"cursor": cursor, "selected": selected}, action


def _browse_ui(stdscr, entries):
    """Render the checkbox picker and drive it until confirm/cancel.

    Returns the selected extension names (possibly empty) on confirm,
    or None on cancel. Scrolls the visible window to keep the cursor
    in view when there are more entries than terminal rows.
    """
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.keypad(True)
    n = len(entries)
    state = {"cursor": 0, "selected": set()}
    top = 0
    while True:
        height, width = stdscr.getmaxyx()
        visible_rows = max(1, height - 1)  # last row reserved for the footer
        if state["cursor"] < top:
            top = state["cursor"]
        elif state["cursor"] >= top + visible_rows:
            top = state["cursor"] - visible_rows + 1
        top = max(0, min(top, max(0, n - visible_rows)))
        stdscr.clear()
        for row, i in enumerate(range(top, min(n, top + visible_rows))):
            e = entries[i]
            mark = "x" if i in state["selected"] else " "
            pointer = ">" if i == state["cursor"] else " "
            status = f"  [{e['status']}]" if e["status"] else ""
            line = f"{pointer} [{mark}] {e['name']:<16} {e['description']}{status}"
            attr = curses.A_REVERSE if i == state["cursor"] else curses.A_NORMAL
            stdscr.addstr(row, 0, line[:max(0, width - 1)], attr)
        footer = "space:toggle  a:all  n:none  enter:install  q:cancel"
        stdscr.addstr(min(visible_rows, height - 1), 0, footer[:max(0, width - 1)])
        stdscr.refresh()
        key = stdscr.getch()
        state, action = _browse_step(state, key, n)
        if action == "confirm":
            return [entries[i]["name"] for i in sorted(state["selected"])]
        if action == "cancel":
            return None


def _run_browse_ui(entries):
    return curses.wrapper(_browse_ui, entries)


def cmd_browse(args):
    if not sys.stdout.isatty():
        print("error: tito browse requires an interactive terminal", file=sys.stderr)
        return 1
    entries = _fetch_manifest()
    if entries is None:
        return 1
    for e in entries:
        e["status"] = _local_status(e["name"])
    selected = _run_browse_ui(entries)
    if selected is None:
        print("cancelled")
        return 0
    if not selected:
        print("nothing selected")
        return 0
    ok_count, failed = 0, []
    for name in selected:
        ok, msg = _do_enable(name)
        if msg:
            print(msg)
        if ok:
            ok_count += 1
        else:
            failed.append(name)
    summary = f"installed {ok_count}/{len(selected)}"
    if failed:
        summary += f", failed: {', '.join(failed)}"
    print(summary)
    return 1 if failed else 0


def cmd_filters(args):
    """List bundled and user extensions (user copies override bundled)."""
    found_any = False
    for label, directory in (("bundled", bundled_extensions_dir()),
                             ("user", filters_dir())):
        if not os.path.isdir(directory):
            continue
        entries = []
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for fn in files:
                if fn.endswith(".py") or fn.endswith(".py.disabled"):
                    entries.append(os.path.relpath(os.path.join(root, fn), directory))
        for rel in sorted(entries):
            found_any = True
            disabled = rel.endswith(".py.disabled")
            name = rel[: -len(".py.disabled")] if disabled else rel[: -len(".py")]
            if name.endswith(os.sep + "default"):
                name = name[: -len(os.sep + "default")]
            status = " (disabled)" if disabled else ""
            print(f"{label}: {name}{status}")
    if not found_any:
        print("no filters installed")
    return 0


def cmd_new_filter(args):
    if not args:
        print("usage: tito new-filter <name>", file=sys.stderr)
        return 1
    name = args[0]
    path = _filter_path(name)
    if path is None:
        return 1
    if os.path.exists(path):
        print(f"error: {path} already exists", file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(FILTER_SKELETON)
    print(f"created {path} — edit COMMANDS and filter()")
    return 0


# --- hook rewriter --------------------------------------------------------

def _split_segments(cmd):
    """Split cmd on && / || / ; outside quotes.

    Returns [(segment_text, separator), ...] or None when the command
    contains constructs we refuse to touch (pipes, substitutions,
    redirections, heredocs, backgrounding, unclosed quotes).
    """
    segs, buf = [], []
    in_single = in_double = False
    i, n = 0, len(cmd)
    while i < n:
        ch = cmd[i]
        nxt = cmd[i + 1] if i + 1 < n else ""
        if in_single:
            buf.append(ch)
            if ch == "'":
                in_single = False
            i += 1
            continue
        if ch == "\\":
            buf.append(cmd[i : i + 2])
            i += 2
            continue
        if in_double:
            if ch == '"':
                in_double = False
            elif ch == "`" or (ch == "$" and nxt == "("):
                return None  # substitution still expands inside double quotes
            buf.append(ch)
            i += 1
            continue
        if ch == "'":
            in_single = True
        elif ch == '"':
            in_double = True
        elif ch == "`" or (ch == "$" and nxt == "("):
            return None  # command substitution
        elif ch in "<>":
            return None  # redirection or heredoc
        elif ch == "&" and nxt == "&":
            segs.append(("".join(buf), "&&"))
            buf = []
            i += 2
            continue
        elif ch == "&":
            return None  # backgrounding
        elif ch == "|" and nxt == "|":
            segs.append(("".join(buf), "||"))
            buf = []
            i += 2
            continue
        elif ch == "|":
            return None  # pipe: downstream consumes raw output
        elif ch == ";":
            segs.append(("".join(buf), ";"))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if in_single or in_double:
        return None
    segs.append(("".join(buf), ""))
    return segs


def _rewrite_segment(text, handled):
    stripped = text.lstrip()
    if not stripped:
        return text
    first = stripped.split()[0]
    if first in ("tito", "rtk") or "=" in first or first not in handled:
        return text
    pad = text[: len(text) - len(stripped)]
    return pad + "tito " + stripped


def rewrite_command(cmd, handled):
    """Prefix handled commands with 'tito '. Doubt favors no rewrite."""
    segments = _split_segments(cmd)
    if segments is None:
        return cmd
    return "".join(_rewrite_segment(text, handled) + sep for text, sep in segments)


def _hook_claude(payload):
    """Claude Code PreToolUse hook body (unchanged behavior)."""
    cmd = payload.get("tool_input", {}).get("command", "")
    if not cmd:
        return
    handled = set(load_registry())
    new = rewrite_command(cmd, handled)
    if new != cmd:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "updatedInput": {**payload.get("tool_input", {}), "command": new},
            }
        }))


def cmd_hook(args):
    """Claude Code PreToolUse hook (reads JSON on stdin).

    Absolute rule: never crash, never block. Any problem -> no output,
    exit 0, the agent runs the original command untouched.
    """
    try:
        payload = json.load(sys.stdin)
        _hook_claude(payload)
    except Exception:
        pass
    return 0


def cmd_rewrite(args):
    """Print the tito-prefixed rewrite of a command, or the command
    unchanged if nothing applies. Always exits 0 — same "never break a
    command" contract as every other tito entry point. Handy for
    debugging the rewrite logic without running a command.
    """
    cmd = None
    try:
        cmd = " ".join(args) if args else sys.stdin.read().rstrip("\n")
        handled = set(load_registry())
        print(rewrite_command(cmd, handled))
    except Exception:
        # doubt favors no rewrite: on any error, echo the input unchanged
        if cmd is not None:
            print(cmd)
    return 0


# --- dispatch -------------------------------------------------------------

def dispatch(argv, registry=None):
    """Run argv through its filter, falling back to raw on any problem."""
    registry = load_registry() if registry is None else registry
    flt = registry.get(argv[0])
    if flt is None:
        try:
            return subprocess.run(argv).returncode
        except FileNotFoundError:
            print(f"tito: {argv[0]}: command not found", file=sys.stderr)
            return 127
    run_argv = list(argv)
    if flt.transform is not None:
        try:
            run_argv = flt.transform(list(argv))
        except Exception:
            run_argv = list(argv)
    try:
        stdout, stderr, code = run(run_argv)
    except FileNotFoundError:
        print(f"tito: {argv[0]}: command not found", file=sys.stderr)
        return 127
    try:
        out = flt.render(argv, stdout, stderr, code)
    except Exception:
        out = None
    if out is None:
        sys.stdout.write(stdout)
        sys.stderr.write(stderr)
        return code
    record_stats(argv[0], len(stdout) + len(stderr), len(out))
    if out and not out.endswith("\n"):
        out += "\n"
    sys.stdout.write(out)
    if code != 0:
        sys.stderr.write(stderr)
    return code


# --- install --------------------------------------------------------------

def load_settings(path):
    """Read a settings JSON file. {} when missing, None when unreadable."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (ValueError, OSError):
        return None


def register_hook(settings, hook_cmd):
    """Add the tito PreToolUse hook to a settings dict. Idempotent."""
    hooks = settings.setdefault("hooks", {}).setdefault("PreToolUse", [])
    for entry in hooks:
        if any("tito" in h.get("command", "") for h in entry.get("hooks", [])):
            return settings
    hooks.append({
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": hook_cmd}],
    })
    return settings


def should_copy(src, target):
    """False when target is already src (running from the installed binary).

    Avoids shutil.SameFileError on `~/.local/bin/tito install` re-runs.
    """
    if not os.path.exists(target):
        return True
    return not os.path.samefile(src, target)


def cmd_install(args):
    """Copy the binary to ~/.local/bin/tito and register the Claude Code hook.

    Order matters: validate ~/.claude/settings.json BEFORE touching the
    binary — a corrupt settings file must fail loudly with nothing copied,
    not half-install.
    """
    settings_path = os.path.expanduser("~/.claude/settings.json")
    settings = load_settings(settings_path)
    if settings is None:
        _say("❌", _RED, f"error: {settings_path} is not valid JSON — fix it and re-run", sys.stderr)
        return 1

    target = os.path.expanduser("~/.local/bin/tito")
    src = os.path.abspath(__file__)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if should_copy(src, target):
        shutil.copy(src, target)
        os.chmod(target, 0o755)
        _say("✅", _GREEN, f"installed {target}")
    else:
        _say("ℹ️ ", _CYAN, f"{target} is already up to date")

    if shutil.which("tito") is None:
        _say(
            "⚠️ ",
            _YELLOW,
            "warning: ~/.local/bin is not on your PATH — the hook will fail "
            "on every handled command until it is.\n"
            '  add this to your shell profile: export PATH="$HOME/.local/bin:$PATH"',
            sys.stderr,
        )

    settings = register_hook(settings, target + " hook")

    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)
    _say("🔧", _CYAN, "Claude Code: hook registered")

    _say("💡", _CYAN, "restart your agent session to activate the hook")
    return 0


# --- main -----------------------------------------------------------------

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(USAGE, end="")
        return 0
    meta = {
        "gain": cmd_gain,
        "filters": cmd_filters,
        "enable": cmd_enable,
        "browse": cmd_browse,
        "disable": cmd_disable,
        "new-filter": cmd_new_filter,
        "hook": cmd_hook,
        "rewrite": cmd_rewrite,
        "install": cmd_install,
    }
    if argv[0] in meta:
        return meta[argv[0]](argv[1:])
    return dispatch(argv)


if __name__ == "__main__":
    sys.exit(main())
