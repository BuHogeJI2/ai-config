from ai_config.skills import discover, read_frontmatter
from tests.helpers import FakeWorldTestCase


class ReadFrontmatterTest(FakeWorldTestCase):
    def test_reads_top_level_fields_and_strips_quotes(self):
        path = self.write(
            self.home / "SKILL.md",
            "---\nname: 'plan'\ndescription: \"Make a plan.\"\nmetadata:\n  nested: ignored\n---\nBody\n",
        )
        self.assertEqual(read_frontmatter(path), {"name": "plan", "description": "Make a plan.", "metadata": ""})

    def test_block_value_returns_its_marker(self):
        path = self.write(self.home / "SKILL.md", "---\nname: x\ndescription: >\n  folded text\n---\n")
        self.assertEqual(read_frontmatter(path)["description"], ">")

    def test_no_frontmatter(self):
        self.assertIsNone(read_frontmatter(self.write(self.home / "SKILL.md", "# Title\n")))

    def test_unclosed_frontmatter(self):
        self.assertIsNone(read_frontmatter(self.write(self.home / "SKILL.md", "---\nname: x\n")))


class DiscoverTest(FakeWorldTestCase):
    def found(self):
        return {(skill.agent, skill.kind, self.env.shorten(skill.path)) for skill in discover(self.env)}

    def test_finds_every_discovery_location(self):
        self.add_skill(self.env.codex_skills, "personal")
        self.add_skill(self.env.codex_legacy_skills, "legacy")
        self.add_skill(self.env.codex_legacy_skills / ".system", "system")
        self.add_skill(self.home / ".codex/plugins/cache/market/tool/1.0/skills", "codex-plugin")
        self.add_skill(self.env.claude_skills, "claude-personal")
        self.add_skill(self.env.claude_skills / "synced/bucket", "synced")
        self.add_skill(self.home / ".claude/plugins/cache/market/tool/skills", "claude-plugin")
        self.add_skill(self.home / ".claude/plugins/synced/bucket/tool/skills", "claude-synced-plugin")

        self.assertEqual(
            self.found(),
            {
                ("codex", "personal", "~/.agents/skills/personal"),
                ("codex", "legacy", "~/.codex/skills/legacy"),
                ("codex", "system", "~/.codex/skills/.system/system"),
                ("codex", "plugin", "~/.codex/plugins/cache/market/tool/1.0/skills/codex-plugin"),
                ("claude", "personal", "~/.claude/skills/claude-personal"),
                ("claude", "synced", "~/.claude/skills/synced/bucket/synced"),
                ("claude", "plugin", "~/.claude/plugins/cache/market/tool/skills/claude-plugin"),
                ("claude", "plugin", "~/.claude/plugins/synced/bucket/tool/skills/claude-synced-plugin"),
            },
        )

    def test_reads_only_the_selected_agents(self):
        self.add_skill(self.env.codex_skills, "codex-personal")
        self.add_skill(self.env.claude_skills, "claude-personal")
        self.add_skill(self.home / ".claude/plugins/cache/market/tool/skills", "claude-plugin")
        found = {(skill.agent, skill.name) for skill in discover(self.env, ("codex",))}
        self.assertEqual(found, {("codex", "codex-personal")})
        found = {(skill.agent, skill.name) for skill in discover(self.env, ("claude",))}
        self.assertEqual(found, {("claude", "claude-personal"), ("claude", "claude-plugin")})

    def test_skips_folders_without_skill_md_and_ignored_places(self):
        (self.env.claude_skills / "empty").mkdir(parents=True)
        self.add_skill(self.home / ".claude/plugins/marketplaces/official/tool/skills", "not-installed")
        self.add_skill(self.home / ".claude/plugins/cache/.trash/tool/skills", "trashed")
        self.add_skill(self.home / ".codex/plugins/cache/tool/node_modules/dep/skills", "dependency")
        self.assertEqual(self.found(), set())

    def test_legacy_folder_that_is_the_install_folder_is_scanned_once(self):
        self.add_skill(self.env.codex_skills, "plan")
        self.link(self.env.codex_legacy_skills, self.env.codex_skills)
        self.assertEqual(self.found(), {("codex", "personal", "~/.agents/skills/plan")})

    def test_follows_skill_links(self):
        source = self.add_skill(self.repo / "shared/skills", "linked")
        self.link(self.env.claude_skills / "linked", source)
        (skill,) = discover(self.env)
        self.assertEqual(skill.path, self.env.claude_skills / "linked")

    def test_names_ignore_case_and_include_declared_name(self):
        self.add_skill(self.env.claude_skills, "Folder", declared_name="Declared")
        (skill,) = discover(self.env)
        self.assertEqual(skill.names, {"folder", "declared"})
