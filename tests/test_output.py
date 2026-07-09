"""Tests for the _paint / _say output helpers."""

import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tito  # noqa: E402


class _Stream(io.StringIO):
    """A StringIO whose isatty() is controllable."""

    def __init__(self, is_tty):
        super().__init__()
        self._is_tty = is_tty

    def isatty(self):
        return self._is_tty


class PaintTests(unittest.TestCase):
    def test_wraps_with_color_when_stream_is_tty(self):
        s = _Stream(is_tty=True)
        self.assertEqual(tito._paint(tito._RED, "hi", s), f"{tito._RED}hi{tito._RESET}")

    def test_plain_when_stream_is_not_tty(self):
        s = _Stream(is_tty=False)
        self.assertEqual(tito._paint(tito._RED, "hi", s), "hi")


class SayTests(unittest.TestCase):
    def test_writes_emoji_space_message_to_stream(self):
        s = _Stream(is_tty=False)
        tito._say("✅", tito._GREEN, "done", stream=s)
        self.assertEqual(s.getvalue(), "✅ done\n")


if __name__ == "__main__":
    unittest.main()
