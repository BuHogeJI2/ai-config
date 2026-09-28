import os
import stat

import ai_config.installer as installer
from ai_config.backups import list_backups, read_meta
from ai_config.fileops import TargetChangedError
from ai_config.planner import KEEP, ORPHAN, RELINK
from ai_config.installer import apply_plan
from ai_config.manifest import parse_manifest
from ai_config.planner import build_plan
from ai_config.state import LinkRecord, load_state
from tests.helpers import FakeWorldTestCase, skill_entry


class InstallerTestCase(FakeWorldTestCase):
    def manifest(self, *entries):
        return parse_manifest({"version": 1, "external": [], "entries": list(entries)})

    def install(self, *entries):
        state = load_state(self.env.state_dir)
        plan = build_plan(self.repo, self.env, self.manifest(*entries), state)
        return apply_plan(plan, self.repo.resolve(), state, self.env.state_dir)

    def assertLinked(self, target, source):
        self.assertTrue(target.is_symlink(), f"{target} is not a link")
        self.assertEqual(os.readlink(target), str(source))


class ApplyTest(InstallerTestCase):
    def test_first_install_creates_links_and_records_state(self):
        source = self.add_skill(self.repo / "shared/skills", "plan")
        self.assertEqual(self.install(skill_entry("shared", "plan")), [])
        self.assertLinked(self.env.codex_skills / "plan", source)
        self.assertLinked(self.env.claude_skills / "plan", source)
        state = load_state(self.env.state_dir)
        self.assertEqual(state.repo_root, self.repo)
        self.assertEqual(state.links[self.env.claude_skills / "plan"], LinkRecord("skill/plan", str(source), self.repo))

    def test_second_install_changes_nothing(self):
        self.add_skill(self.repo / "claude/skills", "plan")
        self.install(skill_entry("claude", "plan"))
        before = os.lstat(self.env.claude_skills / "plan")
        self.assertEqual(self.install(skill_entry("claude", "plan")), [])
        self.assertEqual(os.lstat(self.env.claude_skills / "plan").st_ino, before.st_ino)

    def test_identical_local_copy_is_backed_up_and_replaced(self):
        source = self.add_skill(self.repo / "claude/skills", "plan")
        local = self.add_skill(self.env.claude_skills, "plan")
        self.write(local / "run.sh", "echo\n").chmod(0o755)
        self.write(source / "run.sh", "echo\n").chmod(0o755)

        (backup,) = self.install(skill_entry("claude", "plan"))

        self.assertLinked(local, source)
        self.assertEqual(read_meta(backup.path)["modes"]["run.sh"], 0o755)
        self.assertEqual(stat.S_IMODE((backup.path / "content/run.sh").stat().st_mode), 0o600)
        self.assertEqual([path.name for path in self.env.claude_skills.iterdir()], ["plan"])

    def test_identical_legacy_copy_is_backed_up_and_removed(self):
        source = self.add_skill(self.repo / "codex/skills", "task-plan")
        self.add_skill(self.env.codex_legacy_skills, "task-plan")

        (backup,) = self.install(skill_entry("codex", "task-plan"))

        self.assertLinked(self.env.codex_skills / "task-plan", source)
        self.assertFalse(os.path.lexists(self.env.codex_legacy_skills / "task-plan"))
        self.assertEqual(backup.target, self.env.codex_legacy_skills / "task-plan")
        self.assertNotIn(self.env.codex_legacy_skills / "task-plan", load_state(self.env.state_dir).links)

    def test_relink_backs_up_the_old_link(self):
        source = self.add_skill(self.repo / "claude/skills", "plan")
        old = self.add_skill(self.repo / "shared/skills", "plan")
        self.link(self.env.claude_skills / "plan", old)

        (backup,) = self.install(skill_entry("claude", "plan"))

        self.assertLinked(self.env.claude_skills / "plan", source)
        self.assertEqual(read_meta(backup.path)["link"], str(old))

    def test_plan_with_conflicts_is_refused(self):
        self.add_skill(self.repo / "claude/skills", "plan")
        self.add_skill(self.env.claude_skills, "plan", description="Local edit.")
        with self.assertRaises(ValueError):
            self.install(skill_entry("claude", "plan"))
        self.assertFalse(self.env.state_dir.exists())

    def test_target_changed_after_planning_stops_the_run(self):
        self.add_skill(self.repo / "claude/skills", "plan")
        local = self.add_skill(self.env.claude_skills, "plan")
        plan = build_plan(self.repo, self.env, self.manifest(skill_entry("claude", "plan")))
        self.write(local / "SKILL.md", "edited after planning")

        with self.assertRaises(TargetChangedError):
            apply_plan(plan, self.repo.resolve(), load_state(self.env.state_dir), self.env.state_dir)

        self.assertFalse(local.is_symlink())
        self.assertEqual((local / "SKILL.md").read_text(), "edited after planning")

    def test_moved_checkout_is_relinked_even_when_the_old_checkout_is_gone(self):
        self.add_skill(self.repo / "shared/skills", "plan")
        self.install(skill_entry("shared", "plan"))
        moved = self.repo.parent / "moved-repo"
        self.repo.rename(moved)
        self.repo = moved

        plan = build_plan(self.repo, self.env, self.manifest(skill_entry("shared", "plan")), load_state(self.env.state_dir))
        self.assertEqual({action.kind for action in plan.actions}, {"relink"})
        self.install(skill_entry("shared", "plan"))

        self.assertLinked(self.env.codex_skills / "plan", moved / "shared/skills/plan")
        self.assertLinked(self.env.claude_skills / "plan", moved / "shared/skills/plan")
        self.assertEqual(load_state(self.env.state_dir).repo_root, moved)

    def test_moved_checkout_keeps_changed_and_foreign_links_as_conflicts(self):
        self.add_skill(self.repo / "shared/skills", "plan")
        self.install(skill_entry("shared", "plan"))
        old_root = self.repo
        moved = self.repo.parent / "moved-repo"
        self.repo.rename(moved)
        self.repo = moved
        (self.env.codex_skills / "plan").unlink()
        os.symlink(f"{old_root}/shared/skills/plan/", self.env.codex_skills / "plan")
        (self.env.claude_skills / "plan").unlink()
        os.symlink(self.home / "elsewhere", self.env.claude_skills / "plan")

        plan = build_plan(self.repo, self.env, self.manifest(skill_entry("shared", "plan")), load_state(self.env.state_dir))

        self.assertEqual([action.kind for action in plan.actions], ["conflict", "conflict"])

    def test_orphan_left_in_the_old_checkout_is_found(self):
        self.add_skill(self.repo / "claude/skills", "plan")
        self.install(skill_entry("claude", "plan"))
        moved = self.repo.parent / "moved-repo"
        self.repo.rename(moved)
        self.repo = moved
        plan = build_plan(self.repo, self.env, self.manifest(), load_state(self.env.state_dir))
        self.assertEqual([(action.kind, action.target) for action in plan.actions], [("orphan", self.env.claude_skills / "plan")])

    def test_foreign_link_placed_after_planning_is_kept(self):
        self.add_skill(self.repo / "claude/skills", "plan")
        self.link(self.env.claude_skills / "plan", self.add_skill(self.repo / "shared/skills", "plan"))
        plan = build_plan(self.repo, self.env, self.manifest(skill_entry("claude", "plan")))
        (self.env.claude_skills / "plan").unlink()
        os.symlink(self.home / "foreign", self.env.claude_skills / "plan")

        with self.assertRaises(TargetChangedError):
            apply_plan(plan, self.repo.resolve(), load_state(self.env.state_dir), self.env.state_dir)

        self.assertEqual(os.readlink(self.env.claude_skills / "plan"), str(self.home / "foreign"))
        self.assertEqual(list_backups(self.env.state_dir), [])

    def test_kept_link_changed_after_planning_is_not_recorded(self):
        source = self.add_skill(self.repo / "claude/skills", "plan")
        (self.home / "other").mkdir()
        for change in (
            lambda link: (link.unlink(), os.symlink(self.home / "foreign", link)),
            lambda link: link.unlink(),
            lambda link: (os.rename(self.env.claude_skills, self.home / "other/skills"), self.link(self.env.claude_skills, self.home / "other/skills")),
        ):
            with self.subTest(change=change):
                link = self.env.claude_skills / "plan"
                if self.env.claude_skills.is_symlink():
                    self.env.claude_skills.unlink()
                if os.path.lexists(link):
                    link.unlink()
                self.link(link, source)
                plan = build_plan(self.repo, self.env, self.manifest(skill_entry("claude", "plan")))
                self.assertEqual([action.kind for action in plan.actions], [KEEP])
                change(link)

                with self.assertRaises(TargetChangedError):
                    apply_plan(plan, self.repo.resolve(), load_state(self.env.state_dir), self.env.state_dir)

                self.assertEqual(load_state(self.env.state_dir).links, {})
                if (self.home / "other/skills").exists():
                    (self.home / "other/skills/plan").unlink()
                    (self.home / "other/skills").rmdir()

    def test_parent_swapped_into_repository_after_planning_writes_nothing(self):
        self.add_skill(self.repo / "claude/skills", "plan")
        plan = build_plan(self.repo, self.env, self.manifest(skill_entry("claude", "plan")))
        (self.repo / "empty").mkdir()
        self.link(self.env.claude_skills, self.repo / "empty")

        with self.assertRaises(TargetChangedError):
            apply_plan(plan, self.repo.resolve(), load_state(self.env.state_dir), self.env.state_dir)

        self.assertEqual(list((self.repo / "empty").iterdir()), [])

    def test_special_file_swapped_in_after_planning_is_not_backed_up(self):
        self.add_skill(self.repo / "claude/skills", "plan")
        local = self.add_skill(self.env.claude_skills, "plan")
        plan = build_plan(self.repo, self.env, self.manifest(skill_entry("claude", "plan")))
        (local / "SKILL.md").unlink()
        os.mkfifo(local / "SKILL.md")

        with self.assertRaises(TargetChangedError):
            apply_plan(plan, self.repo.resolve(), load_state(self.env.state_dir), self.env.state_dir)

        self.assertEqual(list_backups(self.env.state_dir), [])

    def test_source_removed_after_planning_writes_nothing(self):
        source = self.add_skill(self.repo / "claude/skills", "plan")
        plan = build_plan(self.repo, self.env, self.manifest(skill_entry("claude", "plan")))
        (source / "SKILL.md").unlink()
        source.rmdir()
        with self.assertRaises(TargetChangedError):
            apply_plan(plan, self.repo.resolve(), load_state(self.env.state_dir), self.env.state_dir)
        self.assertFalse(os.path.lexists(self.env.claude_skills / "plan"))

    def test_target_recreated_during_replace_keeps_both_versions(self):
        self.add_skill(self.repo / "claude/skills", "plan")
        local = self.add_skill(self.env.claude_skills, "plan")
        plan = build_plan(self.repo, self.env, self.manifest(skill_entry("claude", "plan")))
        original = installer.place_symlink

        def someone_else_writes_first(target, link_text, unchanged):
            self.write(target / "SKILL.md", "written by someone else")
            return original(target, link_text, unchanged)

        installer.place_symlink = someone_else_writes_first
        self.addCleanup(setattr, installer, "place_symlink", original)

        with self.assertRaises(TargetChangedError) as caught:
            apply_plan(plan, self.repo.resolve(), load_state(self.env.state_dir), self.env.state_dir)

        self.assertEqual((local / "SKILL.md").read_text(), "written by someone else")
        self.assertIn("the original content is kept at", str(caught.exception))
        asides = [path for path in self.env.claude_skills.iterdir() if path.name.startswith(".plan.ai-config-")]
        self.assertEqual(len(asides), 1)
        self.assertIn("Test skill.", (asides[0] / "SKILL.md").read_text())

    def test_orphan_from_old_checkout_survives_an_install_that_changes_nothing(self):
        self.add_skill(self.repo / "claude/skills", "plan")
        self.install(skill_entry("claude", "plan"))
        moved = self.repo.parent / "moved-repo"
        self.repo.rename(moved)
        self.repo = moved

        self.install()

        plan = build_plan(self.repo, self.env, self.manifest(), load_state(self.env.state_dir))
        self.assertEqual([(action.kind, action.target) for action in plan.actions], [(ORPHAN, self.env.claude_skills / "plan")])

    def test_interrupted_relocation_can_be_retried(self):
        self.add_skill(self.repo / "shared/skills", "plan")
        self.install(skill_entry("shared", "plan"))
        moved = self.repo.parent / "moved-repo"
        self.repo.rename(moved)
        self.repo = moved
        plan = build_plan(self.repo, self.env, self.manifest(skill_entry("shared", "plan")), load_state(self.env.state_dir))
        first_only = type(plan)((plan.actions[0],))
        apply_plan(first_only, self.repo, load_state(self.env.state_dir), self.env.state_dir)

        retry = build_plan(self.repo, self.env, self.manifest(skill_entry("shared", "plan")), load_state(self.env.state_dir))

        self.assertEqual([action.kind for action in retry.actions], [KEEP, RELINK])

    def test_relative_link_is_recorded_as_is_and_relinked_after_a_move(self):
        source = self.add_skill(self.repo / "claude/skills", "plan")
        self.env.claude_skills.mkdir(parents=True)
        relative = os.path.relpath(source, self.env.claude_skills)
        os.symlink(relative, self.env.claude_skills / "plan")
        self.install(skill_entry("claude", "plan"))
        self.assertEqual(load_state(self.env.state_dir).links[self.env.claude_skills / "plan"].link_text, relative)

        moved = self.repo.parent / "moved-repo"
        self.repo.rename(moved)
        self.repo = moved
        plan = build_plan(self.repo, self.env, self.manifest(skill_entry("claude", "plan")), load_state(self.env.state_dir))
        self.assertEqual([action.kind for action in plan.actions], [RELINK])

    def test_backups_are_pruned_to_the_newest_five_per_target(self):
        self.add_skill(self.repo / "claude/skills", "plan")
        for _ in range(7):
            local = self.env.claude_skills / "plan"
            if local.is_symlink():
                local.unlink()
            self.add_skill(self.env.claude_skills, "plan")
            self.install(skill_entry("claude", "plan"))
        self.assertEqual(len(list_backups(self.env.state_dir)), 5)
