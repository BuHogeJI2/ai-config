import os

from ai_config.installer import apply_plan
from ai_config.manifest import parse_manifest
from ai_config.paths import Environment
from ai_config.planner import CREATE, KEEP, ORPHAN, PRUNE, RELINK, build_plan
from ai_config.state import LinkRecord, State, load_state, save_state
from tests.helpers import FakeWorldTestCase, skill_entry

CODEX_ONLY = ("codex",)
CLAUDE_ONLY = ("claude",)
BOTH = ("codex", "claude")
COMPOSE_ENTRY = {
    "id": "instructions/codex",
    "method": "compose",
    "sources": ["shared/instructions.md", "codex/instructions.md"],
    "targets": ["~/.codex/AGENTS.md"],
}
CLAUDE_INSTRUCTIONS = {
    "id": "instructions/claude",
    "method": "symlink",
    "source": "claude/CLAUDE.md",
    "targets": ["~/.claude/CLAUDE.md"],
}


class SelectionTestCase(FakeWorldTestCase):
    def setUp(self):
        super().setUp()
        self.shared = self.add_skill(self.repo / "shared/skills", "planning")
        self.codex_skill = self.add_skill(self.repo / "codex/skills", "task")
        self.claude_skill = self.add_skill(self.repo / "claude/skills", "review")
        self.write(self.repo / "shared/instructions.md", "Shared rule.\n")
        self.write(self.repo / "codex/instructions.md", "Codex rule.\n")
        self.write(self.repo / "claude/CLAUDE.md", "Claude rule.\n")
        self.entries = [
            skill_entry("shared", "planning"),
            skill_entry("codex", "task"),
            skill_entry("claude", "review"),
            COMPOSE_ENTRY,
            CLAUDE_INSTRUCTIONS,
        ]

    def plan(self, agents, prune=False, entries=None):
        manifest = parse_manifest({"version": 1, "external": [], "entries": entries or self.entries})
        return build_plan(self.repo, self.env, manifest, load_state(self.env.state_dir), prune=prune, agents=agents)

    def actions(self, agents, prune=False):
        return {(action.kind, self.env.shorten(action.target)) for action in self.plan(agents, prune).actions}

    def details(self, agents, prune=False):
        return {self.env.shorten(action.target): action.detail for action in self.plan(agents, prune).actions}

    def install(self, agents, prune=False):
        state = load_state(self.env.state_dir)
        manifest = parse_manifest({"version": 1, "external": [], "entries": self.entries})
        plan = build_plan(self.repo, self.env, manifest, state, prune=prune, agents=agents)
        return apply_plan(plan, self.repo.resolve(), state, self.env.state_dir)


class FreshHomeTest(SelectionTestCase):
    def test_codex_only_plans_only_codex_targets(self):
        self.assertEqual(
            self.actions(CODEX_ONLY),
            {
                (CREATE, "~/.agents/skills/planning"),
                (CREATE, "~/.agents/skills/task"),
                (CREATE, "~/.codex/AGENTS.md"),
            },
        )

    def test_codex_only_install_creates_no_claude_folder(self):
        self.install(CODEX_ONLY)
        self.assertFalse(os.path.lexists(self.env.claude_home))
        self.assertTrue((self.env.codex_home / "AGENTS.md").is_file())

    def test_claude_only_plans_only_claude_targets(self):
        self.assertEqual(
            self.actions(CLAUDE_ONLY),
            {
                (CREATE, "~/.claude/skills/planning"),
                (CREATE, "~/.claude/skills/review"),
                (CREATE, "~/.claude/CLAUDE.md"),
            },
        )

    def test_claude_only_leaves_legacy_codex_copies_alone(self):
        self.add_skill(self.env.codex_legacy_skills, "task")
        self.install(CLAUDE_ONLY)
        self.assertTrue((self.env.codex_legacy_skills / "task/SKILL.md").is_file())

    def test_default_is_both_agents(self):
        manifest = parse_manifest({"version": 1, "external": [], "entries": self.entries})
        default = build_plan(self.repo, self.env, manifest)
        self.assertEqual(
            {(a.kind, a.target) for a in default.actions}, {(a.kind, a.target) for a in self.plan(BOTH).actions}
        )


class SwitchingTest(SelectionTestCase):
    def test_disabled_agent_links_and_generated_file_become_orphans(self):
        self.install(BOTH)
        self.assertEqual(
            self.actions(CLAUDE_ONLY),
            {
                (KEEP, "~/.claude/skills/planning"),
                (KEEP, "~/.claude/skills/review"),
                (KEEP, "~/.claude/CLAUDE.md"),
                (ORPHAN, "~/.agents/skills/planning"),
                (ORPHAN, "~/.agents/skills/task"),
                (ORPHAN, "~/.codex/AGENTS.md"),
            },
        )
        self.assertEqual(self.details(CLAUDE_ONLY)["~/.codex/AGENTS.md"], "agent disabled: codex")

    def test_prune_removes_them_and_their_records(self):
        self.install(BOTH)
        backups = self.install(CODEX_ONLY, prune=True)
        for path in ("skills/planning", "skills/review", "CLAUDE.md"):
            self.assertFalse(os.path.lexists(self.env.claude_home / path))
        self.assertEqual(len(backups), 3)
        state = load_state(self.env.state_dir)
        self.assertFalse(any(target.parts[-2:] == ("skills", "review") for target in state.links))
        self.assertIn(self.env.codex_skills / "task", state.links)

    def test_without_prune_nothing_is_removed_and_records_stay(self):
        self.install(BOTH)
        self.install(CODEX_ONLY)
        self.assertTrue((self.env.claude_skills / "review").is_symlink())
        self.assertIn(self.env.claude_skills / "review", load_state(self.env.state_dir).links)

    def test_edited_generated_file_of_disabled_agent_is_kept(self):
        self.install(BOTH)
        (self.env.codex_home / "AGENTS.md").write_text("My edit.\n", encoding="utf-8")
        self.install(CLAUDE_ONLY, prune=True)
        self.assertEqual((self.env.codex_home / "AGENTS.md").read_text(encoding="utf-8"), "My edit.\n")
        self.assertIn(self.env.codex_home / "AGENTS.md", load_state(self.env.state_dir).generated)

    def test_ordinary_content_and_foreign_links_of_disabled_agent_are_left_alone(self):
        self.add_skill(self.env.claude_skills, "review")
        self.link(self.env.claude_skills / "planning", self.home / "elsewhere")
        self.write(self.env.claude_home / "CLAUDE.md", "Local.\n")
        self.assertEqual(
            {kind for kind, target in self.actions(CODEX_ONLY, prune=True) if target.startswith("~/.claude")}, set()
        )

    def test_adding_an_agent_back_creates_its_targets(self):
        self.install(CODEX_ONLY)
        self.assertEqual(
            {(kind, target) for kind, target in self.actions(BOTH) if kind != KEEP},
            {
                (CREATE, "~/.claude/skills/planning"),
                (CREATE, "~/.claude/skills/review"),
                (CREATE, "~/.claude/CLAUDE.md"),
            },
        )


class LocationTest(SelectionTestCase):
    def test_folder_shared_with_an_enabled_target_is_never_cleaned(self):
        self.link(self.env.claude_skills, self.env.codex_skills)
        self.install(CODEX_ONLY)
        self.assertEqual(
            {(kind, target) for kind, target in self.actions(CODEX_ONLY, prune=True) if "skills" in target},
            {(KEEP, "~/.agents/skills/planning"), (KEEP, "~/.agents/skills/task")},
        )

    def test_codex_home_outside_home_follows_the_selection(self):
        codex_home = self.home.parent / "codex-home"
        self.env = Environment.from_env({"HOME": str(self.home), "CODEX_HOME": str(codex_home)})
        self.install(BOTH)
        self.assertTrue((codex_home / "AGENTS.md").is_file())
        plan = self.plan(CLAUDE_ONLY, prune=True)
        pruned = {action.target for action in plan.actions if action.kind == PRUNE}
        self.assertIn(codex_home / "AGENTS.md", pruned)

    def test_disabled_link_from_a_moved_checkout_is_removed_not_relinked(self):
        old_repo = self.home.parent / "old-repo"
        old_source = self.add_skill(old_repo / "claude/skills", "review")
        target = self.env.claude_skills / "review"
        self.link(target, old_source)
        record = LinkRecord("skill/review", str(old_source), old_repo)
        save_state(self.env.state_dir, State(repo_root=old_repo, links={target: record}))
        kinds = {action.kind for action in self.plan(CODEX_ONLY, prune=True).actions if action.target == target}
        self.assertEqual(kinds, {PRUNE})
        self.assertNotIn(RELINK, {action.kind for action in self.plan(CODEX_ONLY).actions if action.target == target})

    def test_generated_record_from_an_old_codex_home_stays_an_orphan(self):
        self.install(BOTH)
        self.env = Environment.from_env({"HOME": str(self.home), "CODEX_HOME": str(self.home / "new-codex")})
        details = {action.target: (action.kind, action.detail) for action in self.plan(CLAUDE_ONLY).actions}
        self.assertEqual(
            details[self.home / ".codex/AGENTS.md"], (ORPHAN, "generated file has no manifest entry")
        )
