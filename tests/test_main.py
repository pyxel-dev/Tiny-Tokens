"""Tests for the top-level dispatch in tito.main()."""

import io
import os
import sys
import unittest
from unittest import mock

# Make the repo-root tito module importable no matter the cwd.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tito  # noqa: E402


class MainDispatchTests(unittest.TestCase):
    def test_no_args_prints_usage_and_returns_zero(self):
        with mock.patch("sys.stdout", new=io.StringIO()) as out:
            rc = tito.main([])
        self.assertEqual(rc, 0)
        self.assertIn("usage:", out.getvalue())

    def test_unknown_command_prints_usage_and_returns_zero(self):
        with mock.patch("sys.stdout", new=io.StringIO()) as out:
            rc = tito.main(["frobnicate", "x"])
        self.assertEqual(rc, 0)
        self.assertIn("usage:", out.getvalue())

    def test_install_dispatches_to_cmd_install(self):
        with mock.patch.object(tito, "cmd_install", return_value=0) as m:
            rc = tito.main(["install"])
        m.assert_called_once_with([])
        self.assertEqual(rc, 0)

    def test_install_passes_through_extra_args(self):
        with mock.patch.object(tito, "cmd_install", return_value=0) as m:
            tito.main(["install", "--force", "yes"])
        m.assert_called_once_with(["--force", "yes"])

    def test_return_code_propagates_from_cmd_install(self):
        with mock.patch.object(tito, "cmd_install", return_value=1):
            rc = tito.main(["install"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
