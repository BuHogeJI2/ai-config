import io
import os
import stat
from unittest import mock

from ai_config.fileops import TargetChangedError
from ai_config.state import exclusive_lock, load_state

import ai_config.cli as cli_module
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

    def test_invalid_manifest(self):
        self.write(self.repo / "manifest.json", "{")
        code, lines = self.run_cli("install", "--dry-run")
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("error    manifest: manifest.json is not valid JSON"))


class InstallTest(FakeWorldTestCase):
    run_cli = InstallDryRunTest.run_cli

    def test_empty_manifest_creates_only_the_private_state_folder(self):
        self.assertEqual(self.run_cli("install"), (0, ["Nothing to change.", "Applied 0 change(s)."]))
        self.assertEqual(sorted(path.name for path in self.env.state_dir.iterdir()), ["lock", "state.json"])
        self.assertEqual(stat.S_IMODE(self.env.state_dir.stat().st_mode), 0o700)
        self.assertEqual(sorted(path.name for path in self.home.iterdir()), [".local"])

    def test_applies_changes_and_lists_backups(self):
        source = self.add_skill(self.repo / "claude/skills", "plan")
        self.add_skill(self.env.claude_skills, "plan")
        self.write_manifest([skill_entry("claude", "plan")])
        code, lines = self.run_cli("install")
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], "replace        ~/.claude/skills/plan: local copy is identical and is backed up first")
        self.assertTrue(lines[2].startswith("backup         ~/.claude/skills/plan: "))
        self.assertEqual(lines[-1], "Applied 1 change(s).")
        self.assertEqual(os.readlink(self.env.claude_skills / "plan"), str(source))

    def test_conflict_writes_nothing(self):
        self.add_skill(self.repo / "claude/skills", "plan")
        self.add_skill(self.repo / "claude/skills", "other")
        self.add_skill(self.env.claude_skills, "plan", description="Local edit.")
        self.write_manifest([skill_entry("claude", "plan"), skill_entry("claude", "other")])
        code, lines = self.run_cli("install")
        self.assertEqual(code, 1)
        self.assertFalse((self.env.claude_skills / "other").exists())
        self.assertFalse(os.path.exists(self.env.state_dir / "state.json"))

    def test_another_run_holding_the_lock_is_an_error(self):
        with exclusive_lock(self.env.state_dir):
            self.assertEqual(self.run_cli("install"), (1, ["error    another ai-config run holds the lock"]))

    def test_invalid_state_is_an_error(self):
        self.write(self.env.state_dir / "state.json", "{")
        code, lines = self.run_cli("install")
        self.assertEqual(code, 1)
        self.assertIn("is not valid JSON", lines[0])


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


class AgentsOptionTest(FakeWorldTestCase):
    run_cli = InstallDryRunTest.run_cli

    def setUp(self):
        super().setUp()
        self.shared = self.add_skill(self.repo / "shared/skills", "plan")
        self.review = self.add_skill(self.repo / "claude/skills", "review")
        self.write_manifest([skill_entry("shared", "plan"), skill_entry("claude", "review")])

    def saved(self):
        return load_state(self.env.state_dir).agents

    def test_install_for_codex_only_saves_the_choice(self):
        code, lines = self.run_cli("install", "--agents", "codex")
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], "agents         codex (--agents)")
        self.assertEqual(lines[-1], "Saved agents: codex. A plain install uses them from now on.")
        self.assertFalse(os.path.lexists(self.env.claude_home))
        self.assertEqual(self.saved(), ("codex",))
        self.assertEqual(
            self.run_cli("install"),
            (0, ["agents         codex (saved)", "ok             ~/.agents/skills/plan", "Nothing to change.", "Applied 0 change(s)."]),
        )

    def test_old_state_without_a_choice_installs_both(self):
        self.run_cli("install")
        self.assertIsNone(self.saved())
        self.assertTrue((self.env.claude_skills / "review").is_symlink())

    def test_dry_run_doctor_and_diff_do_not_save(self):
        self.assertEqual(self.run_cli("install", "--dry-run", "--agents", "codex")[1][0], "agents         codex (--agents)")
        self.assertEqual(self.run_cli("doctor", "--agents", "codex")[1][0], "agents         codex (--agents)")
        self.run_cli("diff", "skill/plan", "--agents", "codex")
        self.assertFalse(os.path.exists(self.env.state_dir / "state.json"))

    def test_invalid_value_is_an_error(self):
        for value in ("gemini", "", "codex,codex"):
            with self.subTest(value=value):
                code, lines = self.run_cli("install", "--agents", value)
                self.assertEqual(code, 1)
                self.assertTrue(lines[0].startswith("error    --agents"), lines)
        self.assertFalse(os.path.exists(self.env.state_dir / "state.json"))

    def test_conflicting_plan_does_not_save(self):
        self.add_skill(self.env.codex_skills, "plan", description="Local edit.")
        self.assertEqual(self.run_cli("install", "--agents", "codex")[0], 1)
        self.assertFalse(os.path.exists(self.env.state_dir / "state.json"))

    def test_failed_install_keeps_the_choice_for_the_retry(self):
        with mock.patch("ai_config.cli.apply_plan", side_effect=TargetChangedError("changed")):
            self.assertEqual(self.run_cli("install", "--agents", "codex")[0], 1)
        self.assertEqual(self.saved(), ("codex",))

    def test_replace_local_of_an_inactive_entry_is_an_error(self):
        code, lines = self.run_cli("install", "--agents", "codex", "--replace-local", "skill/review")
        self.assertEqual(code, 1)
        self.assertEqual(lines[-1], "error    --replace-local: skill/review has no target for the agents codex")
        self.assertFalse(os.path.exists(self.env.state_dir / "state.json"))

    def test_diff_shows_only_selected_targets_and_names_inactive_entries(self):
        self.run_cli("install", "--agents", "codex")
        self.assertEqual(
            self.run_cli("diff", "skill/plan"),
            (0, ["agents         codex (saved)", "~/.agents/skills/plan: linked to shared/skills/plan"]),
        )
        self.assertEqual(
            self.run_cli("diff", "skill/review")[1][-1],
            "skill/review: inactive, it has no target for the agents codex; compare with --agents",
        )
        self.assertEqual(self.run_cli("diff", "skill/review", "--agents", "claude")[1][-1], "~/.claude/skills/review: missing")

    def test_diff_of_a_mixed_agent_compose_entry_reads_only_selected_targets(self):
        self.write(self.repo / "shared/instructions.md", "Shared rule.\n")
        entry = {
            "id": "instructions/both",
            "method": "compose",
            "sources": ["shared/instructions.md"],
            "targets": ["~/.codex/AGENTS.md", "~/.claude/CLAUDE.md"],
        }
        self.write_manifest([entry])
        self.write(self.env.claude_home / "CLAUDE.md", "Private Claude text.\n")
        for argv in (("diff", "instructions/both", "--agents", "codex"), ("diff", "instructions/both")):
            with self.subTest(argv=argv):
                if argv[-1] == "instructions/both":
                    self.run_cli("install", "--agents", "codex")
                with mock.patch("ai_config.cli.read_regular_file", wraps=cli_module.read_regular_file) as read:
                    code, lines = self.run_cli(*argv)
                self.assertEqual(code, 0)
                self.assertFalse(any("CLAUDE.md" in line or "Private" in line for line in lines), lines)
                self.assertNotIn(self.env.claude_home / "CLAUDE.md", [call.args[0] for call in read.call_args_list])

    def backups(self):
        """Backup ids by (kind, target) from the restore listing."""
        return {(line.split()[1], line.split()[2]): line.split()[0] for line in self.run_cli("restore")[1]}

    def test_restore_and_uninstall_keep_the_choice(self):
        self.add_skill(self.env.codex_skills, "plan")
        self.run_cli("install", "--agents", "codex")
        self.assertEqual(self.run_cli("restore", self.backups()[("dir", "~/.agents/skills/plan")])[0], 0)
        self.assertEqual(self.saved(), ("codex",))
        self.run_cli("uninstall")
        self.assertEqual(self.saved(), ("codex",))

    def test_prune_removes_a_restored_repository_link_but_not_a_restored_copy(self):
        self.add_skill(self.env.claude_skills, "review")
        self.run_cli("install")
        self.run_cli("install", "--agents", "codex", "--prune")
        self.assertFalse(os.path.lexists(self.env.claude_skills / "review"))
        backups = self.backups()
        self.assertEqual(self.run_cli("restore", backups[("dir", "~/.claude/skills/review")])[0], 0)
        self.assertEqual(self.run_cli("restore", backups[("link", "~/.claude/skills/plan")])[0], 0)
        self.assertFalse((self.env.claude_skills / "review").is_symlink())
        lines = self.run_cli("install", "--dry-run", "--prune")[1]
        self.assertIn("prune          ~/.claude/skills/plan: agent disabled: claude", lines)
        self.assertFalse(any("~/.claude/skills/review" in line for line in lines), lines)
