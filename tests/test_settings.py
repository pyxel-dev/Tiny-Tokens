"""Tests for load_settings() and register_hook()."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tito  # noqa: E402


def _tmpfile(content=None):
    """Create a temp file (optionally pre-written) and return its path."""
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    if content is not None:
        f.write(content)
        f.flush()
    f.close()
    return f.name


class LoadSettingsTests(unittest.TestCase):
    def test_missing_file_returns_empty_dict(self):
        missing = os.path.join(tempfile.gettempdir(), "tito_does_not_exist.json")
        self.assertEqual(tito.load_settings(missing), {})

    def test_valid_json_returns_parsed_dict(self):
        path = _tmpfile(json.dumps({"hooks": {}}))
        try:
            self.assertEqual(tito.load_settings(path), {"hooks": {}})
        finally:
            os.unlink(path)

    def test_invalid_json_returns_none(self):
        path = _tmpfile("{ not valid json")
        try:
            self.assertIsNone(tito.load_settings(path))
        finally:
            os.unlink(path)

    def test_empty_file_returns_none(self):
        path = _tmpfile("")
        try:
            self.assertIsNone(tito.load_settings(path))
        finally:
            os.unlink(path)


class RegisterHookTests(unittest.TestCase):
    HOOK_CMD = "/home/u/.local/bin/tito hook"

    def test_adds_hook_to_empty_settings(self):
        s = {}
        out = tito.register_hook(s, self.HOOK_CMD)
        # Mutated in place.
        self.assertIs(out, s)
        entries = out["hooks"]["PreToolUse"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["matcher"], "Bash")
        self.assertEqual(entries[0]["hooks"][0]["type"], "command")
        self.assertEqual(entries[0]["hooks"][0]["command"], self.HOOK_CMD)

    def test_idempotent_no_duplicate(self):
        s = tito.register_hook({}, self.HOOK_CMD)
        count_before = len(s["hooks"]["PreToolUse"])
        tito.register_hook(s, self.HOOK_CMD)
        self.assertEqual(len(s["hooks"]["PreToolUse"]), count_before)

    def test_preserves_existing_pretooluse_hooks(self):
        existing = {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Edit", "hooks": [{"type": "command", "command": "other"}]}
                ]
            }
        }
        out = tito.register_hook(existing, self.HOOK_CMD)
        entries = out["hooks"]["PreToolUse"]
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["matcher"], "Edit")  # untouched
        self.assertEqual(entries[1]["matcher"], "Bash")

    def test_recognizes_existing_tito_hook_with_different_path(self):
        # Any command containing "tito" counts as already registered.
        s = {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [{"type": "command", "command": "/elsewhere/tito hook"}]}
                ]
            }
        }
        out = tito.register_hook(s, "/new/path/tito hook")
        self.assertEqual(len(out["hooks"]["PreToolUse"]), 1)


if __name__ == "__main__":
    unittest.main()
