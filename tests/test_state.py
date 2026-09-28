import os
import stat
from pathlib import Path

from ai_config.backups import create_backup, list_backups, prune_backups, read_meta
from ai_config.state import LinkRecord, State, StateError, exclusive_lock, load_state, save_state
from tests.helpers import FakeWorldTestCase


def mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


class StateFileTest(FakeWorldTestCase):
    def test_missing_state_is_empty(self):
        self.assertEqual(load_state(self.env.state_dir), State())

    def test_round_trip_with_private_modes(self):
        state = State(repo_root=self.repo, links={self.home / "a": LinkRecord("skill/a", "/repo/a", self.repo)})
        save_state(self.env.state_dir, state)
        self.assertEqual(load_state(self.env.state_dir), state)
        self.assertEqual(mode(self.env.state_dir), 0o700)
        self.assertEqual(mode(self.env.state_dir / "state.json"), 0o600)

    def test_invalid_state_is_an_error(self):
        for text in (
            "{",
            '{"version": 2}',
            '{"version": 1, "links": {"/a": {"entry": "x"}}}',
            '{"version": 1, "repo_root": 42, "links": {}}',
            '{"version": 1, "repo_root": "relative", "links": {}}',
            '{"version": 1, "links": []}',
            '{"version": 1, "links": {"relative": {"entry": "x", "link": "/r/x", "repo_root": "/r"}}}',
            '{"version": 1, "links": {"/a": {"entry": 1, "link": "/r/x", "repo_root": "/r"}}}',
            '{"version": 1, "links": {"/a": {"entry": "x", "link": "", "repo_root": "/r"}}}',
            '{"version": 1, "links": {"/a": {"entry": "x", "link": "/r/x", "repo_root": null}}}',
        ):
            with self.subTest(text=text):
                self.write(self.env.state_dir / "state.json", text)
                with self.assertRaises(StateError):
                    load_state(self.env.state_dir)

    def test_lock_is_exclusive(self):
        with exclusive_lock(self.env.state_dir):
            with self.assertRaises(StateError):
                with exclusive_lock(self.env.state_dir):
                    pass
        with exclusive_lock(self.env.state_dir):
            pass


class BackupTest(FakeWorldTestCase):
    def test_folder_backup_is_private_and_keeps_original_modes(self):
        skill = self.add_skill(self.env.claude_skills, "plan")
        script = self.write(skill / "scripts/run.sh", "echo\n")
        script.chmod(0o755)
        (skill / "alias.md").symlink_to("SKILL.md")

        backup = create_backup(self.env.state_dir, skill)

        content = backup.path / "content"
        self.assertEqual(mode(self.env.state_dir / "backups"), 0o700)
        self.assertEqual(mode(backup.path), 0o700)
        self.assertEqual(mode(content), 0o700)
        self.assertEqual(mode(content / "scripts/run.sh"), 0o600)
        self.assertEqual(mode(backup.path / "meta.json"), 0o600)
        self.assertEqual((content / "SKILL.md").read_text(), (skill / "SKILL.md").read_text())
        self.assertEqual(os.readlink(content / "alias.md"), "SKILL.md")
        meta = read_meta(backup.path)
        self.assertEqual(meta["target"], str(skill))
        self.assertEqual(meta["kind"], "dir")
        self.assertEqual(meta["modes"]["scripts/run.sh"], 0o755)

    def test_link_backup_keeps_link_text(self):
        link = self.env.claude_skills / "plan"
        self.link(link, self.repo / "claude/skills/plan")
        backup = create_backup(self.env.state_dir, link)
        self.assertEqual(read_meta(backup.path)["link"], str(self.repo / "claude/skills/plan"))
        self.assertFalse((backup.path / "content").exists())

    def test_prune_keeps_the_newest_per_target(self):
        first = self.write(self.home / "first.md", "x")
        second = self.write(self.home / "second.md", "y")
        created = [create_backup(self.env.state_dir, first) for _ in range(7)]
        other = create_backup(self.env.state_dir, second)

        removed = prune_backups(self.env.state_dir, first, keep=5)

        self.assertEqual([backup.id for backup in removed], [backup.id for backup in created[:2]])
        remaining = [backup.id for backup in list_backups(self.env.state_dir)]
        self.assertEqual(remaining, [backup.id for backup in created[2:]] + [other.id])
