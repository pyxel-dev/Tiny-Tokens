"""Tests for the bundled git extension (extensions/git/default.py).

Loads the extension file directly and exercises its filter()/transform(),
then confirms the registry picks it up as a bundled extension.
"""

import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tito  # noqa: E402


def _load_git_extension():
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "extensions", "git", "default.py",
    )
    spec = importlib.util.spec_from_file_location("tito_git_ext_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GitTransformTests(unittest.TestCase):
    def setUp(self):
        self.git = _load_git_extension()

    def test_status_transform_adds_porcelain(self):
        self.assertEqual(
            self.git.transform(["git", "status"]),
            ["git", "status", "--porcelain=v1", "-b"],
        )

    def test_log_transform_adds_format(self):
        self.assertEqual(
            self.git.transform(["git", "log"]),
            ["git", "log", "--format=%h %ad %s", "--date=short"],
        )

    def test_transform_left_alone_when_porcelain_present(self):
        out = self.git.transform(["git", "status", "--porcelain=v2"])
        self.assertEqual(out, ["git", "status", "--porcelain=v2"])

    def test_transform_left_alone_for_unknown_subcommand(self):
        self.assertEqual(self.git.transform(["git", "stash"]), ["git", "stash"])


class GitFilterTests(unittest.TestCase):
    def setUp(self):
        self.git = _load_git_extension()

    def test_error_code_passes_through_raw(self):
        self.assertIsNone(self.git.filter(["git", "status"], "err", "err", 1))

    def test_clean_status(self):
        self.assertEqual(self.git.filter(["git", "status"], "## main\n", "", 0), "main clean")

    def test_status_lists_changed_files(self):
        out = self.git.filter(
            ["git", "status"],
            "## main\n## origin/main\nM  a.py\n?? b.txt\n",
            "", 0,
        )
        self.assertEqual(out, "main\norigin/main\nM  a.py\n?? b.txt")

    def test_diff_keeps_hunks_and_changes_only(self):
        diff = "diff --git a/a.py b/a.py\nindex 1..2\n@@ -1,2 +1,2 @@\n-old\n+new\n ctx\n"
        self.assertEqual(
            self.git.filter(["git", "diff"], diff, "", 0),
            "=== a.py\n@@ -1,2 +1,2 @@\n-old\n+new",
        )

    def test_diff_empty_is_no_diff(self):
        self.assertEqual(self.git.filter(["git", "diff"], "", "", 0), "no diff")

    def test_add_confirms_ok(self):
        self.assertEqual(self.git.filter(["git", "add", "."], "", "", 0), "ok")

    def test_push_confirms(self):
        self.assertEqual(self.git.filter(["git", "push"], "", "", 0), "ok pushed")

    def test_commit_confirms_with_ref_and_summary(self):
        stdout = "[main abc1234] msg\n 1 file changed, 1 insertion(+)\n"
        self.assertEqual(
            self.git.filter(["git", "commit"], stdout, "", 0),
            "ok [main abc1234] 1 file changed, 1 insertion(+)",
        )

    def test_log_passes_through_verbatim(self):
        self.assertEqual(self.git.filter(["git", "log"], "abc1234 x\n", "", 0), "abc1234 x\n")


class GitRegistryTests(unittest.TestCase):
    def test_bundled_git_is_loaded_by_registry(self):
        reg = tito.load_registry()
        self.assertIn("git", reg)

    def test_resolve_user_overrides_bundled(self):
        # _resolve picks the last-loaded filter, so a user extension
        # (loaded after bundled) wins for the same command.
        bundled = tito.Filter(["git"], lambda *a: "bundled", source="b")
        user = tito.Filter(["git"], lambda *a: "user", source="u")
        resolved = tito._resolve([bundled, user])
        self.assertEqual(resolved.render(["git"], "", "", 0), "user")


if __name__ == "__main__":
    unittest.main()
