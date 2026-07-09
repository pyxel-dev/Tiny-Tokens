#!/usr/bin/env python3

import json
import os
import shutil
import sys

# --- Menu -----------------------------------------------------------------

USAGE = """
usage: tito <command> [args...]   run a command with filtered output
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


# --- install -----------------------------------------------------------

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
        "install": cmd_install,
    }
    if argv[0] in meta:
        return meta[argv[0]](argv[1:])
    print(USAGE, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
