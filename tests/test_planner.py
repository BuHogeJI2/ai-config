import os

from ai_config.manifest import parse_manifest
from ai_config.paths import Environment
from ai_config.planner import CONFLICT, CREATE, KEEP, ORPHAN, RELINK, REMOVE_LEGACY, REPLACE, build_plan
from tests.helpers import FakeWorldTestCase, skill_entry


class PlannerTestCase(FakeWorldTestCase):
    def plan(self, *entries):
        manifest = parse_manifest({"version": 1, "external": [], "entries": list(entries)})
        return build_plan(self.repo, self.env, manifest)

    def actions(self, *entries):
        return {(action.kind, self.env.shorten(action.target)) for action in self.plan(*entries).actions}

    def repo_skill(self, owner, name, **kwargs):
        return self.add_skill(self.repo / owner / "skills", name, **kwargs)


class LinkActionsTest(PlannerTestCase):
    def test_missing_targets_are_created(self):
        self.repo_skill("shared", "plan")
        self.assertEqual(
            self.actions(skill_entry("shared", "plan")),
            {(CREATE, "~/.agents/skills/plan"), (CREATE, "~/.claude/skills/plan")},
        )

    def test_correct_link_is_kept(self):
        source = self.repo_skill("claude", "plan")
        self.link(self.env.claude_skills / "plan", source)
        self.assertEqual(self.actions(skill_entry("claude", "plan")), {(KEEP, "~/.claude/skills/plan")})

    def test_relative_correct_link_is_kept(self):
        source = self.repo_skill("claude", "plan")
        self.env.claude_skills.mkdir(parents=True)
        os.symlink(os.path.relpath(source, self.env.claude_skills), self.env.claude_skills / "plan")
        self.assertEqual(self.actions(skill_entry("claude", "plan")), {(KEEP, "~/.claude/skills/plan")})

    def test_identical_local_copy_is_replaced(self):
        self.repo_skill("claude", "plan")
        self.add_skill(self.env.claude_skills, "plan")
        self.assertEqual(self.actions(skill_entry("claude", "plan")), {(REPLACE, "~/.claude/skills/plan")})

    def test_different_local_copy_is_a_conflict(self):
        self.repo_skill("claude", "plan")
        self.add_skill(self.env.claude_skills, "plan", description="Local edit.")
        self.assertEqual(self.actions(skill_entry("claude", "plan")), {(CONFLICT, "~/.claude/skills/plan")})

    def test_link_to_another_repository_path_is_relinked(self):
        self.repo_skill("claude", "plan")
        old = self.repo_skill("shared", "plan")
        self.link(self.env.claude_skills / "plan", old)
        self.assertEqual(self.actions(skill_entry("claude", "plan")), {(RELINK, "~/.claude/skills/plan")})

    def test_broken_link_into_repository_is_relinked(self):
        self.repo_skill("claude", "plan")
        self.link(self.env.claude_skills / "plan", self.repo / "claude/skills/renamed")
        self.assertEqual(self.actions(skill_entry("claude", "plan")), {(RELINK, "~/.claude/skills/plan")})

    def test_foreign_or_broken_links_are_conflicts(self):
        self.repo_skill("shared", "plan")
        elsewhere = self.add_skill(self.home / "elsewhere", "plan")
        self.link(self.env.claude_skills / "plan", elsewhere)
        self.link(self.env.codex_skills / "plan", self.home / "missing")
        plan = self.plan(skill_entry("shared", "plan"))
        details = sorted(action.detail for action in plan.conflicts)
        self.assertEqual(len(details), 2)
        self.assertTrue(details[0].startswith("broken link to"))
        self.assertTrue(details[1].startswith("link points outside this repository"))

    def test_missing_source_is_a_conflict(self):
        self.assertEqual(self.actions(skill_entry("claude", "plan")), {(CONFLICT, "~/.claude/skills/plan")})

    def test_source_resolving_outside_repository_is_a_conflict(self):
        outside = self.add_skill(self.home / "outside/skills", "plan").parent
        (self.repo / "claude").mkdir()
        os.symlink(outside, self.repo / "claude/skills")
        (action,) = self.plan(skill_entry("claude", "plan")).actions
        self.assertEqual(action.kind, CONFLICT)
        self.assertTrue(action.detail.startswith("repository source resolves outside the repository"))

    def test_target_folder_aliased_into_repository_is_a_conflict(self):
        self.repo_skill("codex", "plan")
        self.link(self.env.codex_skills, self.repo / "codex/skills")
        (action,) = self.plan(skill_entry("codex", "plan")).actions
        self.assertEqual(action.kind, CONFLICT)
        self.assertTrue(action.detail.startswith("target location resolves into the repository"))

    def test_legacy_folder_aliased_into_repository_is_a_conflict(self):
        source = self.repo_skill("codex", "plan")
        self.env.codex_home.mkdir()
        self.link(self.env.codex_legacy_skills, self.repo / "codex/skills")
        actions = self.plan(skill_entry("codex", "plan")).actions
        self.assertEqual([action.kind for action in actions], [CREATE, CONFLICT])
        self.assertTrue(actions[1].detail.startswith("legacy Codex copy location resolves into the repository"))
        self.assertTrue(source.is_dir())

    def test_legacy_folder_aliased_to_claude_skills_is_a_conflict(self):
        self.repo_skill("shared", "plan")
        self.add_skill(self.env.claude_skills, "plan")
        self.env.codex_home.mkdir()
        self.link(self.env.codex_legacy_skills, self.env.claude_skills)
        plan = self.plan(skill_entry("shared", "plan"))
        self.assertEqual(
            {(action.kind, self.env.shorten(action.target)) for action in plan.actions},
            {(CREATE, "~/.agents/skills/plan"), (REPLACE, "~/.claude/skills/plan"), (CONFLICT, "~/.codex/skills/plan")},
        )
        self.assertEqual(plan.conflicts[0].detail, f"legacy Codex copy same location as {self.env.claude_skills / 'plan'}")

    def test_targets_aliased_to_the_same_location_are_a_conflict(self):
        self.repo_skill("shared", "plan")
        self.env.codex_skills.mkdir(parents=True)
        self.link(self.env.claude_skills, self.env.codex_skills)
        plan = self.plan(skill_entry("shared", "plan"))
        self.assertEqual([action.kind for action in plan.actions], [CREATE, CONFLICT])
        self.assertEqual(plan.conflicts[0].detail, f"target same location as {self.env.codex_skills / 'plan'}")

    def test_unreadable_local_copy_is_a_conflict(self):
        self.repo_skill("claude", "plan")
        local = self.add_skill(self.env.claude_skills, "plan")
        (local / "locked").mkdir()
        (local / "locked").chmod(0)
        self.addCleanup((local / "locked").chmod, 0o755)
        (action,) = self.plan(skill_entry("claude", "plan")).actions
        self.assertEqual(action.kind, CONFLICT)
        self.assertTrue(action.detail.startswith("cannot read: cannot read"), action.detail)

    def test_compose_target_is_planned_as_a_file(self):
        self.write(self.repo / "codex/instructions.md", "x")
        entry = {"id": "i", "method": "compose", "sources": ["codex/instructions.md"], "targets": ["~/.codex/AGENTS.md"]}
        (action,) = self.plan(entry).actions
        self.assertEqual(action.kind, CREATE)
        self.assertTrue(action.output.endswith("\n\nx\n"))


class LegacyCodexCopyTest(PlannerTestCase):
    def test_identical_legacy_copy_is_removed(self):
        self.repo_skill("codex", "task-plan")
        self.add_skill(self.env.codex_legacy_skills, "task-plan")
        self.assertEqual(
            self.actions(skill_entry("codex", "task-plan")),
            {(CREATE, "~/.agents/skills/task-plan"), (REMOVE_LEGACY, "~/.codex/skills/task-plan")},
        )

    def test_different_legacy_copy_is_a_conflict(self):
        self.repo_skill("codex", "task-plan")
        self.add_skill(self.env.codex_legacy_skills, "task-plan", description="Old.")
        self.assertIn((CONFLICT, "~/.codex/skills/task-plan"), self.actions(skill_entry("codex", "task-plan")))

    def test_legacy_link_to_the_source_is_removed_without_orphan(self):
        source = self.repo_skill("codex", "task-plan")
        self.link(self.env.codex_legacy_skills / "task-plan", source)
        self.assertEqual(
            self.actions(skill_entry("codex", "task-plan")),
            {(CREATE, "~/.agents/skills/task-plan"), (REMOVE_LEGACY, "~/.codex/skills/task-plan")},
        )

    def test_legacy_folder_follows_codex_home(self):
        self.env = Environment.from_env({"HOME": str(self.home), "CODEX_HOME": str(self.home / "custom-codex")})
        self.repo_skill("codex", "task-plan")
        self.add_skill(self.home / "custom-codex/skills", "task-plan")
        self.add_skill(self.home / ".codex/skills", "task-plan", description="Not loaded with this CODEX_HOME.")
        self.assertEqual(
            self.actions(skill_entry("codex", "task-plan")),
            {(CREATE, "~/.agents/skills/task-plan"), (REMOVE_LEGACY, "~/custom-codex/skills/task-plan")},
        )

    def test_no_legacy_cleanup_when_codex_home_holds_the_install_folder(self):
        self.env = Environment.from_env({"HOME": str(self.home), "CODEX_HOME": str(self.home / ".agents")})
        source = self.repo_skill("codex", "task-plan")
        self.link(self.env.codex_skills / "task-plan", source)
        self.assertEqual(self.actions(skill_entry("codex", "task-plan")), {(KEEP, "~/.agents/skills/task-plan")})

    def test_no_legacy_cleanup_when_the_legacy_folder_is_an_alias(self):
        source = self.repo_skill("codex", "task-plan")
        self.link(self.env.codex_skills / "task-plan", source)
        self.link(self.env.codex_legacy_skills, self.env.codex_skills)
        self.assertEqual(self.actions(skill_entry("codex", "task-plan")), {(KEEP, "~/.agents/skills/task-plan")})

    def test_claude_targets_ignore_the_legacy_folder(self):
        self.repo_skill("claude", "plan")
        self.add_skill(self.env.codex_legacy_skills, "plan", description="Codex copy.")
        self.assertEqual(self.actions(skill_entry("claude", "plan")), {(CREATE, "~/.claude/skills/plan")})


class OrphanTest(PlannerTestCase):
    def test_links_into_repository_without_entry_are_orphans(self):
        source = self.repo_skill("claude", "old")
        self.link(self.env.claude_skills / "old", source)
        self.link(self.env.codex_skills / "gone", self.repo / "codex/skills/gone")
        self.link(self.env.claude_home / "rules/shared.md", self.repo / "shared/instructions.md")
        self.assertEqual(
            self.actions(),
            {
                (ORPHAN, "~/.claude/skills/old"),
                (ORPHAN, "~/.agents/skills/gone"),
                (ORPHAN, "~/.claude/rules/shared.md"),
            },
        )

    def test_protected_external_and_unsupported_entries_are_never_orphans(self):
        source = self.repo_skill("claude", "old")
        for link in (
            self.env.codex_skills / "agterm",
            self.env.claude_skills / "Synced",
            self.env.codex_legacy_skills / ".system",
            self.env.codex_legacy_skills / "old",
            self.env.claude_home / "rules/notes.txt",
            self.env.claude_home / "settings.json",
            self.env.codex_home / "config.toml",
        ):
            self.link(link, source)
        self.link(self.env.claude_home / "CLAUDE.md", self.repo / "claude/CLAUDE.md")
        self.link(self.env.codex_home / "AGENTS.md", self.repo / "codex/AGENTS.md")
        manifest = parse_manifest({"version": 1, "external": ["agterm"], "entries": []})
        actions = {(action.kind, self.env.shorten(action.target)) for action in build_plan(self.repo, self.env, manifest).actions}
        self.assertEqual(actions, {(ORPHAN, "~/.claude/CLAUDE.md"), (ORPHAN, "~/.codex/AGENTS.md")})

    def test_managed_link_seen_through_an_aliased_folder_is_not_an_orphan(self):
        source = self.repo_skill("codex", "plan")
        self.link(self.env.codex_skills / "plan", source)
        self.link(self.env.claude_skills, self.env.codex_skills)
        self.assertEqual(self.actions(skill_entry("codex", "plan")), {(KEEP, "~/.agents/skills/plan")})

    def test_orphan_seen_through_two_folders_is_reported_once(self):
        source = self.repo_skill("codex", "old")
        self.link(self.env.codex_skills / "old", source)
        self.link(self.env.claude_skills, self.env.codex_skills)
        self.assertEqual(self.actions(), {(ORPHAN, "~/.agents/skills/old")})

    def test_foreign_links_and_real_folders_are_not_orphans(self):
        self.link(self.env.claude_skills / "foreign", self.home / "elsewhere")
        self.add_skill(self.env.claude_skills, "local")
        self.assertEqual(self.actions(), set())
