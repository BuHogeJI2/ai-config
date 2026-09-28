import os

from ai_config.trees import TreeError, describe_differences, identical
from tests.helpers import FakeWorldTestCase


class TreeComparisonTest(FakeWorldTestCase):
    def make_tree(self, root):
        self.write(root / "SKILL.md", "---\nname: x\n---\n")
        script = self.write(root / "scripts/run.sh", "echo hi\n")
        script.chmod(0o755)
        return root

    def test_same_content_is_identical(self):
        self.assertTrue(identical(self.make_tree(self.home / "a"), self.make_tree(self.home / "b")))

    def test_ds_store_is_ignored(self):
        first, second = self.make_tree(self.home / "a"), self.make_tree(self.home / "b")
        self.write(second / ".DS_Store", "finder")
        self.assertTrue(identical(first, second))

    def test_content_extra_files_and_executable_bit_matter(self):
        first = self.make_tree(self.home / "a")
        for change in (
            lambda root: self.write(root / "SKILL.md", "changed"),
            lambda root: self.write(root / "extra.md", "x"),
            lambda root: (root / "scripts/run.sh").chmod(0o644),
            lambda root: (root / "empty").mkdir(),
        ):
            second = self.make_tree(self.home / f"b{id(change)}")
            change(second)
            self.assertFalse(identical(first, second))

    def test_nested_links_compare_by_link_text(self):
        first, second = self.make_tree(self.home / "a"), self.make_tree(self.home / "b")
        os.symlink("SKILL.md", first / "alias.md")
        os.symlink("SKILL.md", second / "alias.md")
        self.assertTrue(identical(first, second))
        os.remove(second / "alias.md")
        os.symlink("scripts/run.sh", second / "alias.md")
        self.assertFalse(identical(first, second))

    def test_unreadable_folder_is_an_error_not_identical(self):
        first, second = self.home / "a", self.home / "b"
        self.write(first / "locked/file", "x")
        (second / "locked").mkdir(parents=True)
        (first / "locked").chmod(0)
        self.addCleanup((first / "locked").chmod, 0o755)
        with self.assertRaises(TreeError):
            identical(first, second)

    def test_special_files_are_errors_and_are_not_opened(self):
        (self.home / "empty").mkdir()
        os.mkfifo(self.home / "fifo")
        with self.assertRaises(TreeError):
            identical(self.home / "fifo", self.home / "empty")
        (self.home / "tree").mkdir()
        os.mkfifo(self.home / "tree/pipe")
        with self.assertRaises(TreeError):
            identical(self.home / "tree", self.home / "empty")

    def test_missing_path_is_an_error(self):
        with self.assertRaises(TreeError):
            identical(self.home / "missing", self.home / "missing-too")

    def test_single_files(self):
        first = self.write(self.home / "a.md", "same")
        self.assertTrue(identical(first, self.write(self.home / "b.md", "same")))
        self.assertFalse(identical(first, self.write(self.home / "c.md", "other")))


class DescribeDifferencesTest(FakeWorldTestCase):
    def test_lists_every_kind_of_difference(self):
        local, repo = self.home / "local", self.home / "repo"
        self.write(local / "SKILL.md", "one\ntwo\n")
        self.write(repo / "SKILL.md", "one\nthree\n")
        self.write(local / "only-local.md", "x")
        self.write(repo / "only-repo.md", "x")
        self.write(local / "run.sh", "echo\n").chmod(0o755)
        self.write(repo / "run.sh", "echo\n").chmod(0o644)
        self.write(local / "data.bin", "\0a")
        self.write(repo / "data.bin", "\0b")

        lines = describe_differences(local, repo, "local", "repo")

        self.assertIn("--- local/SKILL.md", lines)
        self.assertIn("+++ repo/SKILL.md", lines)
        self.assertIn("-two", lines)
        self.assertIn("+three", lines)
        self.assertIn("only in local: only-local.md", lines)
        self.assertIn("only in repo: only-repo.md", lines)
        self.assertIn("executable bit differs: run.sh", lines)
        self.assertIn("binary files differ: local/data.bin and repo/data.bin", lines)

    def test_undecodable_bytes_are_a_binary_difference(self):
        first = self.write(self.home / "a.txt", "")
        second = self.write(self.home / "b.txt", "")
        first.write_bytes(b"\xff")
        second.write_bytes(b"\xfe")
        self.assertEqual(describe_differences(first, second, "a", "b"), ["binary files differ: a and b"])

    def test_changed_nested_link_shows_both_link_texts(self):
        first, second = self.home / "a", self.home / "b"
        first.mkdir()
        second.mkdir()
        os.symlink("one.md", first / "alias.md")
        os.symlink("two.md", second / "alias.md")
        self.assertEqual(
            describe_differences(first, second, "a", "b"),
            ["link differs: alias.md (-> one.md in a, -> two.md in b)"],
        )

    def test_identical_trees_have_no_lines(self):
        self.write(self.home / "a/SKILL.md", "x")
        self.write(self.home / "b/SKILL.md", "x")
        self.assertEqual(describe_differences(self.home / "a", self.home / "b", "a", "b"), [])
