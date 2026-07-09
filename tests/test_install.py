"""Tests for should_copy() and the cmd_install() flow.

cmd_install touches ~/.local/bin and ~/.claude/settings.json, so each
integration test isolates it by redirecting "~" to a temp HOME and pointing
tito.__file__ at a fake source file. No real install ever happens.

_say's default stream is bound at import time, so rather than fight stdout
capture we record _say calls directly (it's a module global resolved at call
time, hence patchable).
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tito  # noqa: E402


# --- should_copy -----------------------------------------------------------

class ShouldCopyTests(unittest.TestCase):
    def test_true_when_target_missing(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "src")
            open(src, "w").close()
            self.assertTrue(tito.should_copy(src, os.path.join(d, "missing")))

    def test_false_when_same_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "f")
            open(p, "w").close()
            self.assertFalse(tito.should_copy(p, p))

    def test_true_when_different_files(self):
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a")
            b = os.path.join(d, "b")
            open(a, "w").close()
            open(b, "w").close()
            self.assertTrue(tito.should_copy(a, b))


# --- helpers ---------------------------------------------------------------

@contextlib.contextmanager
def _fake_env(which_returns=None):
    """Redirect ~ to a temp HOME and tito.__file__ to a fake source.

    Yields a dict with home/src/settings/target paths. The real settings.json
    and ~/.local/bin/tito stay untouched.
    """
    with tempfile.TemporaryDirectory() as home:
        src_dir = os.path.join(home, "repo")
        os.makedirs(src_dir)
        src = os.path.join(src_dir, "tito.py")
        with open(src, "w") as f:
            f.write("#!/usr/bin/env python3\n")

        settings_path = os.path.join(home, ".claude", "settings.json")
        target = os.path.join(home, ".local", "bin", "tito")

        def fake_expanduser(path):
            return home + path[1:] if path.startswith("~") else path

        with mock.patch("tito.os.path.expanduser", side_effect=fake_expanduser), \
                mock.patch.object(tito, "__file__", src), \
                mock.patch("tito.shutil.which", return_value=which_returns):
            yield {"home": home, "src": src, "settings": settings_path, "target": target}


@contextlib.contextmanager
def _record_say():
    """Record every _say() call as (emoji, message) tuples."""
    calls = []

    def fake(emoji, color, msg, stream=sys.stdout):
        calls.append((emoji, msg))

    with mock.patch("tito._say", fake):
        yield calls


def _tito_hook_count(settings_path):
    with open(settings_path) as f:
        s = json.load(f)
    return sum(
        1
        for entry in s["hooks"]["PreToolUse"]
        for h in entry.get("hooks", [])
        if "tito" in h.get("command", "")
    )


# --- cmd_install (isolated) ------------------------------------------------

class CmdInstallTests(unittest.TestCase):
    def test_corrupt_settings_returns_1_and_copies_nothing(self):
        # All assertions run inside the with-block: _fake_env's tempdir is
        # torn down on exit, so files only exist while it's open.
        with _fake_env() as env, _record_say() as calls:
            os.makedirs(os.path.dirname(env["settings"]), exist_ok=True)
            with open(env["settings"], "w") as f:
                f.write("{ broken")
            rc = tito.cmd_install([])

            self.assertEqual(rc, 1)
            # Golden rule: nothing copied when settings are bad.
            self.assertFalse(os.path.exists(env["target"]))
            self.assertTrue(any("not valid JSON" in m for _, m in calls))

    def test_clean_install_copies_binary_and_registers_hook(self):
        with _fake_env() as env, _record_say() as calls:
            rc = tito.cmd_install([])

            self.assertEqual(rc, 0)
            self.assertTrue(os.path.isfile(env["target"]))
            self.assertTrue(os.access(env["target"], os.X_OK))  # chmod 0o755
            self.assertTrue(os.path.isfile(env["settings"]))
            self.assertEqual(_tito_hook_count(env["settings"]), 1)
            self.assertTrue(any("installed" in m for _, m in calls))

    def test_rerun_from_installed_path_is_idempotent(self):
        with _fake_env() as env, _record_say() as calls:
            tito.cmd_install([])  # first install
            self.assertEqual(_tito_hook_count(env["settings"]), 1)

            # Re-run as if invoked from the installed binary itself.
            with mock.patch.object(tito, "__file__", env["target"]):
                rc = tito.cmd_install([])

            self.assertEqual(rc, 0)
            self.assertTrue(any("up to date" in m for _, m in calls))
            # No duplicate hook on re-run.
            self.assertEqual(_tito_hook_count(env["settings"]), 1)

    def test_warns_when_tito_not_on_path(self):
        with _fake_env(which_returns=None) as env, _record_say() as calls:
            rc = tito.cmd_install([])
            self.assertEqual(rc, 0)
            self.assertTrue(any("PATH" in m for _, m in calls))

    def test_no_path_warning_when_tito_on_path(self):
        with _fake_env(which_returns="/already/here/tito") as env, _record_say() as calls:
            rc = tito.cmd_install([])
            self.assertEqual(rc, 0)
            self.assertFalse(any("PATH" in m for _, m in calls))


if __name__ == "__main__":
    unittest.main()
