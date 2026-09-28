import io
from contextlib import redirect_stderr

from ai_config.cli import main
from tests.helpers import FakeWorldTestCase, skill_entry


class DoctorCommandTest(FakeWorldTestCase):
    def run_doctor(self):
        out = io.StringIO()
        code = main(["doctor"], environ={"HOME": str(self.home)}, repo_root=self.repo, out=out)
        return code, out.getvalue()

    def test_clean_run_exits_zero(self):
        self.assertEqual(self.run_doctor(), (0, "0 error(s), 0 warning(s)\n"))

    def test_errors_exit_one_and_are_listed_first(self):
        self.add_skill(self.env.claude_skills, "plan")
        self.add_skill(self.repo / "claude/skills", "orphan")
        code, output = self.run_doctor()
        self.assertEqual(code, 1)
        self.assertEqual(
            output.splitlines(),
            [
                "error    claude/skills/orphan: skill has no manifest entry",
                "info     unmanaged claude skill: ~/.claude/skills/plan",
                "1 error(s), 0 warning(s)",
            ],
        )


class InstallDryRunTest(FakeWorldTestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        code = main(list(argv), environ={"HOME": str(self.home)}, repo_root=self.repo, out=out)
        return code, out.getvalue().splitlines()

    def test_empty_manifest_has_nothing_to_change(self):
        self.assertEqual(self.run_cli("install", "--dry-run"), (0, ["Nothing to change."]))

    def test_prints_planned_changes(self):
        self.add_skill(self.repo / "claude/skills", "plan")
        self.write_manifest([skill_entry("claude", "plan")])
        self.assertEqual(
            self.run_cli("install", "--dry-run"),
            (0, ["create         ~/.claude/skills/plan -> claude/skills/plan", "1 change(s) planned."]),
        )

    def test_conflict_exits_one_and_points_to_diff(self):
        self.add_skill(self.repo / "claude/skills", "plan")
        self.add_skill(self.env.claude_skills, "plan", description="Local edit.")
        self.write_manifest([skill_entry("claude", "plan")])
        code, lines = self.run_cli("install", "--dry-run")
        self.assertEqual(code, 1)
        self.assertEqual(
            lines,
            [
                "conflict       ~/.claude/skills/plan: local content differs from the repository (see: ai-config diff skill/plan)",
                "1 conflict(s): install changes nothing until they are resolved.",
            ],
        )

    def test_orphans_are_reported(self):
        self.link(self.env.claude_skills / "old", self.repo / "claude/skills/old")
        code, lines = self.run_cli("install", "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(lines[-2:], ["1 orphan link(s): removed only with --prune.", "Nothing to change."])

    def test_install_without_dry_run_is_not_available_yet(self):
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            main(["install"], environ={"HOME": str(self.home)}, repo_root=self.repo)

    def test_invalid_manifest(self):
        self.write(self.repo / "manifest.json", "{")
        code, lines = self.run_cli("install", "--dry-run")
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("error    manifest: manifest.json is not valid JSON"))


class DiffTest(FakeWorldTestCase):
    run_cli = InstallDryRunTest.run_cli

    def test_shows_each_target_state_and_differences(self):
        source = self.add_skill(self.repo / "shared/skills", "plan")
        self.link(self.env.codex_skills / "plan", source)
        self.add_skill(self.env.claude_skills, "plan", description="Local edit.")
        self.add_skill(self.env.codex_legacy_skills, "plan")
        self.write_manifest([skill_entry("shared", "plan")])

        code, lines = self.run_cli("diff", "skill/plan")

        self.assertEqual(code, 0)
        self.assertEqual(lines[0], "~/.agents/skills/plan: linked to shared/skills/plan")
        self.assertEqual(lines[1], "~/.claude/skills/plan: differs from shared/skills/plan")
        self.assertIn("-description: Local edit.", lines)
        self.assertIn("+description: Test skill.", lines)
        self.assertEqual(lines[-1], "~/.codex/skills/plan: identical to shared/skills/plan")

    def test_missing_target(self):
        self.add_skill(self.repo / "claude/skills", "plan")
        self.write_manifest([skill_entry("claude", "plan")])
        self.assertEqual(self.run_cli("diff", "skill/plan"), (0, ["~/.claude/skills/plan: missing"]))

    def test_unreadable_target_is_reported(self):
        self.add_skill(self.repo / "claude/skills", "plan")
        local = self.add_skill(self.env.claude_skills, "plan")
        (local / "locked").mkdir()
        (local / "locked").chmod(0)
        self.addCleanup((local / "locked").chmod, 0o755)
        self.write_manifest([skill_entry("claude", "plan")])
        code, lines = self.run_cli("diff", "skill/plan")
        self.assertEqual(code, 0)
        self.assertTrue(lines[0].startswith("~/.claude/skills/plan: cannot compare: cannot read"))

    def test_unknown_entry(self):
        self.assertEqual(self.run_cli("diff", "nope"), (1, ["error    no manifest entry 'nope'"]))
