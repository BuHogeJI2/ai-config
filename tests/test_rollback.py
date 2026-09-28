import io
import os
from pathlib import Path

from ai_config.cli import main
from ai_config.planner import CONFLICT, ORPHAN, PRUNE, REMOVE_LEGACY, REPLACE
from ai_config.state import load_state
from tests.helpers import FakeWorldTestCase, skill_entry


def home_tree(home: Path) -> dict:
    """Every path under home except the tool's state, with type, content, mode, and link text."""
    tree = {}
    for current, dirs, files in os.walk(home):
        dirs[:] = [name for name in dirs if Path(current, name) != home / ".local"]
        for name in dirs + files:
            path = Path(current, name)
            info = path.lstat()
            if path.is_symlink():
                tree[str(path.relative_to(home))] = ("link", os.readlink(path))
            elif path.is_dir():
                tree[str(path.relative_to(home))] = ("dir", info.st_mode)
            else:
                tree[str(path.relative_to(home))] = ("file", info.st_mode, path.read_bytes())
    return tree


class CliTestCase(FakeWorldTestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        code = main(list(argv), environ={"HOME": str(self.home)}, repo_root=self.repo, out=out)
        return code, out.getvalue().splitlines()

    def backup_ids(self, lines):
        return [line.rsplit(": ", 1)[1] for line in lines if line.startswith("backup ")]


class FullRollbackCycleTest(CliTestCase):
    def test_install_prune_and_restore_return_the_home_to_its_original_state(self):
        for folder in (self.env.codex_legacy_skills, self.env.claude_skills):
            skill = self.add_skill(folder, "plan")
            self.write(skill / "scripts/run.sh", "echo\n").chmod(0o750)
        source = self.add_skill(self.repo / "shared/skills", "plan")
        self.write(source / "scripts/run.sh", "echo\n").chmod(0o750)
        self.env.codex_skills.mkdir(parents=True)
        original = home_tree(self.home)

        self.write_manifest([skill_entry("shared", "plan")])
        code, lines = self.run_cli("install")
        self.assertEqual(code, 0, lines)
        install_backups = self.backup_ids(lines)
        self.assertEqual(len(install_backups), 2)
        self.assertTrue((self.env.claude_skills / "plan").is_symlink())
        self.assertFalse(os.path.lexists(self.env.codex_legacy_skills / "plan"))

        self.write_manifest()
        code, lines = self.run_cli("install", "--prune")
        self.assertEqual(code, 0, lines)
        self.assertFalse(os.path.lexists(self.env.codex_skills / "plan"))
        self.assertFalse(os.path.lexists(self.env.claude_skills / "plan"))

        for backup_id in install_backups:
            self.assertEqual(self.run_cli("restore", backup_id)[0], 0)

        self.assertEqual(home_tree(self.home), original)
        self.assertEqual(load_state(self.env.state_dir).links, {})


class PruneTest(CliTestCase):
    def test_orphans_are_reported_without_prune_and_removed_with_it(self):
        source = self.add_skill(self.repo / "claude/skills", "old")
        self.write_manifest([skill_entry("claude", "old")])
        self.run_cli("install")
        self.write_manifest()

        code, lines = self.run_cli("install", "--dry-run")
        self.assertTrue(lines[0].startswith(f"{ORPHAN:<14} ~/.claude/skills/old"))
        code, lines = self.run_cli("install", "--prune", "--dry-run")
        self.assertTrue(lines[0].startswith(f"{PRUNE:<14} ~/.claude/skills/old"))
        self.assertTrue((self.env.claude_skills / "old").is_symlink())

        code, lines = self.run_cli("install", "--prune")
        self.assertEqual(code, 0)
        self.assertFalse(os.path.lexists(self.env.claude_skills / "old"))
        self.assertEqual(load_state(self.env.state_dir).links, {})
        self.assertTrue(source.is_dir())

    def test_prune_never_touches_foreign_links_or_real_folders(self):
        self.link(self.env.claude_skills / "foreign", self.home / "elsewhere")
        self.add_skill(self.env.claude_skills, "local")
        before = home_tree(self.home)
        self.assertEqual(self.run_cli("install", "--prune")[0], 0)
        self.assertEqual(home_tree(self.home), before)


class ReplaceLocalTest(CliTestCase):
    def test_different_local_copy_legacy_copy_and_foreign_link_are_replaced_with_backups(self):
        source = self.add_skill(self.repo / "shared/skills", "plan")
        self.add_skill(self.env.codex_legacy_skills, "plan", description="Old Codex copy.")
        self.link(self.env.claude_skills / "plan", self.home / "elsewhere")
        self.write_manifest([skill_entry("shared", "plan")])

        code, lines = self.run_cli("install")
        self.assertEqual(code, 1)

        code, lines = self.run_cli("install", "--replace-local", "skill/plan")
        self.assertEqual(code, 0, lines)
        self.assertEqual(os.readlink(self.env.claude_skills / "plan"), str(source))
        self.assertEqual(os.readlink(self.env.codex_skills / "plan"), str(source))
        self.assertFalse(os.path.lexists(self.env.codex_legacy_skills / "plan"))
        self.assertEqual(len(self.backup_ids(lines)), 2)
        self.assertTrue(any(line.startswith(f"{REPLACE:<14} ~/.claude/skills/plan") for line in lines))
        self.assertTrue(any(line.startswith(f"{REMOVE_LEGACY:<14} ~/.codex/skills/plan") for line in lines))

    def test_unsafe_conflicts_stay_conflicts(self):
        self.add_skill(self.repo / "codex/skills", "plan")
        self.link(self.env.codex_skills, self.repo / "codex/skills")
        self.write_manifest([skill_entry("codex", "plan")])
        code, lines = self.run_cli("install", "--replace-local", "skill/plan")
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith(f"{CONFLICT:<14} ~/.agents/skills/plan: target location resolves"))

    def test_only_named_entries_are_replaced(self):
        for name in ("plan", "other"):
            self.add_skill(self.repo / "claude/skills", name)
            self.add_skill(self.env.claude_skills, name, description="Local edit.")
        self.write_manifest([skill_entry("claude", "plan"), skill_entry("claude", "other")])
        code, lines = self.run_cli("install", "--replace-local", "skill/plan")
        self.assertEqual(code, 1)
        self.assertFalse((self.env.claude_skills / "plan").is_symlink())

    def test_unknown_entry_is_an_error(self):
        self.assertEqual(
            self.run_cli("install", "--replace-local", "nope"),
            (1, ["error    --replace-local: no manifest entry nope"]),
        )


class UninstallTest(CliTestCase):
    def test_removes_only_unchanged_recorded_links(self):
        for name in ("plan", "changed", "gone"):
            self.add_skill(self.repo / "claude/skills", name)
        self.write_manifest([skill_entry("claude", name) for name in ("plan", "changed", "gone")])
        self.run_cli("install")
        (self.env.claude_skills / "changed").unlink()
        os.symlink(self.home / "elsewhere", self.env.claude_skills / "changed")
        (self.env.claude_skills / "gone").unlink()
        self.add_skill(self.env.claude_skills, "local")

        code, lines = self.run_cli("uninstall")

        self.assertEqual(code, 1)
        self.assertIn("removed        ~/.claude/skills/plan", lines)
        self.assertIn("kept           ~/.claude/skills/changed: the link was changed after install", lines)
        self.assertEqual(sorted(path.name for path in self.env.claude_skills.iterdir()), ["changed", "local"])
        self.assertEqual(list(load_state(self.env.state_dir).links), [self.env.claude_skills / "changed"])


class RestoreCommandTest(CliTestCase):
    def test_lists_backups_and_reports_errors(self):
        self.assertEqual(self.run_cli("restore"), (0, ["No backups."]))
        self.add_skill(self.repo / "claude/skills", "plan")
        self.add_skill(self.env.claude_skills, "plan")
        self.write_manifest([skill_entry("claude", "plan")])
        (backup_id,) = self.backup_ids(self.run_cli("install")[1])

        code, lines = self.run_cli("restore")
        self.assertEqual(lines, [f"{backup_id}  dir   ~/.claude/skills/plan"])
        self.assertEqual(self.run_cli("restore", "nope"), (1, ["error    no backup 'nope'"]))
        self.assertEqual(self.run_cli("restore", backup_id), (0, ["restored: ~/.claude/skills/plan"]))
        self.assertEqual(self.run_cli("restore", backup_id), (0, ["already restored: ~/.claude/skills/plan"]))
