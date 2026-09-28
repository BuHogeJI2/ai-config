import os
import stat

import ai_config.restore as restore_module
from ai_config.backups import create_backup
from ai_config.fileops import TargetChangedError
from ai_config.restore import RestoreError, restore_backup
from ai_config.state import LinkRecord, State, load_state, save_state
from ai_config.uninstall import uninstall
from tests.helpers import FakeWorldTestCase


class RestoreTest(FakeWorldTestCase):
    def local_skill(self):
        skill = self.add_skill(self.env.claude_skills, "plan")
        self.write(skill / "run.sh", "echo\n").chmod(0o750)
        os.symlink("SKILL.md", skill / "alias.md")
        return skill

    def restore(self, backup_id):
        return restore_backup(backup_id, load_state(self.env.state_dir), self.env.state_dir, self.repo)

    def test_restores_missing_folder_with_original_modes(self):
        skill = self.local_skill()
        backup = create_backup(self.env.state_dir, skill)
        original = sorted((p.relative_to(skill), p.lstat().st_mode) for p in skill.rglob("*"))
        for path in sorted(skill.rglob("*"), reverse=True):
            path.unlink() if not path.is_dir() or path.is_symlink() else path.rmdir()
        skill.rmdir()

        result = self.restore(backup.id)

        self.assertEqual(result.outcome, "restored")
        self.assertEqual(sorted((p.relative_to(skill), p.lstat().st_mode) for p in skill.rglob("*")), original)
        self.assertEqual(stat.S_IMODE((skill / "run.sh").stat().st_mode), 0o750)
        self.assertEqual(os.readlink(skill / "alias.md"), "SKILL.md")

    def test_replaces_a_managed_link_and_forgets_its_record(self):
        skill = self.local_skill()
        backup = create_backup(self.env.state_dir, skill)
        content = (skill / "SKILL.md").read_text()
        for path in sorted(skill.rglob("*"), reverse=True):
            path.unlink() if not path.is_dir() or path.is_symlink() else path.rmdir()
        skill.rmdir()
        source = self.add_skill(self.repo / "claude/skills", "plan")
        os.symlink(source, skill)
        save_state(self.env.state_dir, State(self.repo, {skill: LinkRecord("skill/plan", str(source), self.repo)}))

        self.restore(backup.id)

        self.assertFalse(skill.is_symlink())
        self.assertEqual((skill / "SKILL.md").read_text(), content)
        self.assertEqual(load_state(self.env.state_dir).links, {})
        self.assertTrue(source.is_dir())

    def test_restores_a_link_backup(self):
        link = self.env.claude_skills / "plan"
        self.link(link, self.home / "elsewhere")
        backup = create_backup(self.env.state_dir, link)
        link.unlink()
        self.restore(backup.id)
        self.assertEqual(os.readlink(link), str(self.home / "elsewhere"))

    def test_identical_content_is_already_restored(self):
        skill = self.local_skill()
        backup = create_backup(self.env.state_dir, skill)
        self.assertEqual(self.restore(backup.id).outcome, "already restored")

    def test_different_local_content_is_refused(self):
        skill = self.local_skill()
        backup = create_backup(self.env.state_dir, skill)
        self.write(skill / "SKILL.md", "edited")
        with self.assertRaises(RestoreError):
            self.restore(backup.id)
        self.assertEqual((skill / "SKILL.md").read_text(), "edited")

    def test_foreign_link_is_refused(self):
        skill = self.local_skill()
        backup = create_backup(self.env.state_dir, skill)
        os.rename(skill, self.home / "moved")
        os.symlink(self.home / "moved", skill)
        with self.assertRaises(RestoreError):
            self.restore(backup.id)

    def test_unknown_or_unsafe_ids_are_refused(self):
        for backup_id in ("nope", "..", "../backups", "."):
            with self.subTest(backup_id=backup_id), self.assertRaises(RestoreError):
                self.restore(backup_id)


class RestoreSafetyTest(FakeWorldTestCase):
    def installed_file(self):
        """A local CLAUDE.md that was backed up and replaced by a recorded link into the repository."""
        target = self.write(self.env.claude_home / "CLAUDE.md", "local instructions\n")
        target.chmod(0o644)
        backup = create_backup(self.env.state_dir, target)
        target.unlink()
        source = self.write(self.repo / "claude/CLAUDE.md", "repo instructions\n")
        os.symlink(source, target)
        save_state(self.env.state_dir, State(self.repo, {target: LinkRecord("instructions/claude", str(source), self.repo)}))
        return target, source, backup

    def restore(self, backup_id):
        return restore_backup(backup_id, load_state(self.env.state_dir), self.env.state_dir, self.repo)

    def patch(self, name, replacement):
        original = getattr(restore_module, name)
        setattr(restore_module, name, replacement(original))
        self.addCleanup(setattr, restore_module, name, original)

    def test_recorded_link_replaced_by_a_foreign_link_is_refused(self):
        target, _, backup = self.installed_file()
        target.unlink()
        os.symlink(self.home / "foreign", target)
        with self.assertRaises(RestoreError):
            self.restore(backup.id)
        self.assertEqual(os.readlink(target), str(self.home / "foreign"))

    def test_link_swapped_while_staging_is_kept(self):
        target, _, backup = self.installed_file()

        def swap_then_stage(original):
            def stage(*args):
                target.unlink()
                os.symlink(self.home / "foreign", target)
                return original(*args)
            return stage

        self.patch("_stage", swap_then_stage)
        with self.assertRaises(TargetChangedError):
            self.restore(backup.id)
        self.assertEqual(os.readlink(target), str(self.home / "foreign"))

    def test_file_created_after_the_link_is_moved_aside_is_not_overwritten(self):
        target, source, backup = self.installed_file()

        def move_then_someone_writes(original):
            def move(path, unchanged):
                aside = original(path, unchanged)
                path.write_text("new edit\n")
                return aside
            return move

        self.patch("move_aside", move_then_someone_writes)
        with self.assertRaisesRegex(TargetChangedError, "previous link is kept at"):
            self.restore(backup.id)
        self.assertEqual(target.read_text(), "new edit\n")
        asides = [path for path in target.parent.iterdir() if path.name.startswith(".CLAUDE.md.ai-config-")]
        self.assertEqual([os.readlink(path) for path in asides], [str(source)])

    def test_failed_placement_puts_the_link_back(self):
        target, source, backup = self.installed_file()

        def fail(original):
            def place(staged, destination):
                raise OSError("disk full")
            return place

        self.patch("_place_without_overwriting", fail)
        with self.assertRaises(OSError):
            self.restore(backup.id)
        self.assertEqual(os.readlink(target), str(source))
        self.assertEqual(sorted(path.name for path in target.parent.iterdir()), ["CLAUDE.md"])

    def aliased_into(self, root):
        target, source, backup = self.installed_file()
        link_text = os.readlink(target)
        os.rename(self.env.claude_home, self.home / "real-claude")
        (root / "sub").mkdir(parents=True, exist_ok=True)
        os.symlink(link_text, root / "sub/CLAUDE.md")
        os.symlink(root / "sub", self.env.claude_home)
        return target, backup, root / "sub/CLAUDE.md"

    def test_restore_refuses_a_location_inside_the_repository(self):
        _, backup, inside = self.aliased_into(self.repo)
        with self.assertRaisesRegex(RestoreError, "resolves into a repository checkout"):
            self.restore(backup.id)
        self.assertTrue(inside.is_symlink())

    def test_uninstall_keeps_links_whose_location_is_inside_a_checkout(self):
        for root in (self.repo, self.home / "old-checkout"):
            with self.subTest(root=root):
                self.setUp()
                if root != self.repo:
                    root = self.home / "old-checkout"
                    root.mkdir()
                _, _, inside = self.aliased_into(root)
                if root != self.repo:
                    state = load_state(self.env.state_dir)
                    record = next(iter(state.links.values()))
                    state.links = {key: LinkRecord(record.entry_id, record.link_text, root) for key in state.links}
                    save_state(self.env.state_dir, state)

                result = uninstall(load_state(self.env.state_dir), self.env.state_dir, self.repo)

                self.assertEqual(result.removed, [])
                self.assertIn("resolves into a repository checkout", result.kept[0][1])
                self.assertTrue(inside.is_symlink())

    def test_already_restored_content_gets_its_modes_back_and_loses_its_record(self):
        target, source, backup = self.installed_file()
        target.unlink()
        target.write_text("local instructions\n")
        target.chmod(0o600)

        self.assertEqual(self.restore(backup.id).outcome, "already restored")

        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)
        self.assertEqual(load_state(self.env.state_dir).links, {})

    def restored_file_with_wrong_mode(self):
        target, _, backup = self.installed_file()
        target.unlink()
        target.write_text("local instructions\n")
        target.chmod(0o600)
        return target, backup

    def test_already_restored_path_refuses_a_file_replaced_after_comparison(self):
        target, backup = self.restored_file_with_wrong_mode()

        def replace_file(original):
            def compare(*args):
                result = original(*args)
                target.unlink()
                target.write_text("replaced\n")
                target.chmod(0o600)
                return result
            return compare

        self.patch("_content_matches", replace_file)
        with self.assertRaises(TargetChangedError):
            self.restore(backup.id)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(len(load_state(self.env.state_dir).links), 1)

    def test_already_restored_path_refuses_a_parent_redirected_into_the_repository(self):
        _, backup = self.restored_file_with_wrong_mode()
        authored = self.write(self.repo / "sub/CLAUDE.md", "local instructions\n")
        authored.chmod(0o600)

        def redirect_parent(original):
            def compare(*args):
                result = original(*args)
                os.rename(self.env.claude_home, self.home / "real-claude")
                os.symlink(self.repo / "sub", self.env.claude_home)
                return result
            return compare

        self.patch("_content_matches", redirect_parent)
        with self.assertRaises(TargetChangedError):
            self.restore(backup.id)
        self.assertEqual(stat.S_IMODE(authored.stat().st_mode), 0o600)
        self.assertEqual(len(load_state(self.env.state_dir).links), 1)
