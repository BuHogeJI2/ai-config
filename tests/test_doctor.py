from ai_config.doctor import ERROR, INFO, WARNING, run_doctor
from tests.helpers import FakeWorldTestCase, skill_entry

FAKE_API_KEY = "sk-" + "a1B2" * 8


class DoctorTestCase(FakeWorldTestCase):
    def findings(self, level=None):
        return [
            finding.message
            for finding in run_doctor(self.repo, self.env)
            if level is None or finding.level == level
        ]

    def assertFinding(self, level, fragment):
        messages = self.findings(level)
        self.assertTrue(any(fragment in message for message in messages), f"{fragment!r} not in {messages}")


class CleanStateTest(DoctorTestCase):
    def test_empty_repository_and_home_have_no_findings(self):
        self.assertEqual(self.findings(), [])

    def test_managed_skill_is_clean(self):
        source = self.add_skill(self.repo / "shared/skills", "plan")
        self.write_manifest([skill_entry("shared", "plan")])
        self.link(self.env.codex_skills / "plan", source)
        self.link(self.env.claude_skills / "plan", source)
        self.assertEqual(self.findings(), [])


class ManifestChecksTest(DoctorTestCase):
    def test_invalid_manifest_is_an_error(self):
        self.write(self.repo / "manifest.json", "{")
        self.assertFinding(ERROR, "manifest: manifest.json is not valid JSON")

    def test_missing_source(self):
        self.write_manifest([skill_entry("claude", "gone")])
        self.assertFinding(ERROR, "source does not exist: claude/skills/gone")

    def test_skill_targets_must_match_owner(self):
        self.add_skill(self.repo / "codex/skills", "plan")
        self.write_manifest([skill_entry("codex", "plan", targets=["~/.claude/skills/plan"])])
        self.assertFinding(ERROR, "targets must be ~/.agents/skills/plan for codex/skills/plan")

    def test_skills_must_be_symlinked(self):
        self.add_skill(self.repo / "claude/skills", "plan")
        entry = skill_entry("claude", "plan")
        entry["method"] = "compose"
        entry["sources"] = [entry.pop("source")]
        self.write_manifest([entry])
        self.assertFinding(ERROR, "skills must use the symlink method")


class RepositorySkillChecksTest(DoctorTestCase):
    def test_skill_without_manifest_entry(self):
        self.add_skill(self.repo / "claude/skills", "plan")
        self.assertFinding(ERROR, "claude/skills/plan: skill has no manifest entry")

    def test_external_skill_in_repository(self):
        self.add_skill(self.repo / "shared/skills", "agterm")
        self.write_manifest(external=["agterm"])
        self.assertFinding(ERROR, "shared/skills/agterm: external skills must not be in the repository")

    def test_required_metadata(self):
        self.write(self.repo / "claude/skills/plan/SKILL.md", "---\nname: plan\n---\n")
        self.write(self.repo / "claude/skills/bare/SKILL.md", "# No frontmatter\n")
        (self.repo / "claude/skills/empty").mkdir()
        self.write_manifest([skill_entry("claude", name) for name in ("plan", "bare", "empty")])
        self.assertFinding(ERROR, "claude/skills/plan: SKILL.md frontmatter has no 'description'")
        self.assertFinding(ERROR, "claude/skills/bare: SKILL.md has no frontmatter")
        self.assertFinding(ERROR, "claude/skills/empty: SKILL.md is missing")

    def test_declared_name_must_match_folder(self):
        self.add_skill(self.repo / "claude/skills", "plan", declared_name="planner")
        self.write_manifest([skill_entry("claude", "plan")])
        self.assertFinding(ERROR, "SKILL.md name 'planner' differs from the folder name")


class DuplicateChecksTest(DoctorTestCase):
    def test_duplicate_across_codex_locations_ignores_case(self):
        self.add_skill(self.env.codex_skills, "Backlog")
        self.add_skill(self.env.codex_legacy_skills, "backlog")
        self.assertFinding(ERROR, "duplicate codex skill 'backlog': ~/.agents/skills/Backlog, ~/.codex/skills/backlog")

    def test_duplicate_by_declared_name(self):
        self.add_skill(self.env.claude_skills, "plan")
        self.add_skill(self.env.claude_skills / "synced/bucket", "other", declared_name="plan")
        self.assertFinding(ERROR, "duplicate claude skill 'plan'")

    def test_duplicate_is_reported_once_per_group(self):
        self.add_skill(self.env.claude_skills, "plan")
        self.add_skill(self.env.claude_skills / "synced/bucket", "plan")
        self.assertEqual(len([m for m in self.findings(ERROR) if "duplicate" in m]), 1)

    def test_same_name_in_different_agents_is_fine(self):
        self.add_skill(self.env.codex_legacy_skills, "plan")
        self.add_skill(self.env.claude_skills, "plan")
        self.assertEqual(self.findings(ERROR), [])

    def test_plugin_collision_is_a_warning(self):
        self.add_skill(self.env.codex_legacy_skills, "visualize")
        self.add_skill(self.home / ".codex/plugins/cache/market/visualize/1.0/skills", "visualize")
        self.assertFinding(WARNING, "codex skill 'visualize' is also a plugin skill")
        self.assertEqual(self.findings(ERROR), [])


class LocalSkillChecksTest(DoctorTestCase):
    def test_unmanaged_skills_are_reported(self):
        self.add_skill(self.env.codex_legacy_skills, "task-plan")
        self.add_skill(self.env.codex_skills, "styles-handling")
        self.add_skill(self.env.claude_skills, "plan")
        self.assertFinding(INFO, "unmanaged codex skill: ~/.codex/skills/task-plan")
        self.assertFinding(INFO, "unmanaged codex skill: ~/.agents/skills/styles-handling")
        self.assertFinding(INFO, "unmanaged claude skill: ~/.claude/skills/plan")

    def test_system_synced_and_plugin_skills_are_not_reported(self):
        self.add_skill(self.env.codex_legacy_skills / ".system", "skill-creator")
        self.add_skill(self.env.claude_skills / "synced/bucket", "docs")
        self.assertEqual(self.findings(), [])

    def test_link_into_repository_without_entry_is_an_orphan(self):
        source = self.add_skill(self.repo / "claude/skills", "plan")
        self.link(self.env.claude_skills / "plan", source)
        self.assertFinding(WARNING, "orphan link ~/.claude/skills/plan")
        self.assertFalse(any("unmanaged" in message for message in self.findings()))

    def test_external_skills(self):
        self.write_manifest(external=["agterm"])
        self.add_skill(self.env.codex_legacy_skills, "agterm")
        self.add_skill(self.repo / "elsewhere", "agterm")
        self.link(self.env.claude_skills / "agterm", self.repo / "elsewhere/agterm")
        self.assertFinding(INFO, "external codex skill: ~/.codex/skills/agterm")
        self.assertFinding(WARNING, "external claude skill links into this repository: ~/.claude/skills/agterm")
        self.assertFalse(any("unmanaged" in message for message in self.findings()))


class InstallPlanChecksTest(DoctorTestCase):
    def test_pending_install_is_info(self):
        self.add_skill(self.repo / "claude/skills", "plan")
        self.write_manifest([skill_entry("claude", "plan")])
        self.assertFinding(INFO, "install pending (create) at ~/.claude/skills/plan")
        self.assertEqual(self.findings(ERROR), [])

    def test_conflict_is_an_error(self):
        self.add_skill(self.repo / "claude/skills", "plan")
        self.add_skill(self.env.claude_skills, "plan", description="Local edit.")
        self.write_manifest([skill_entry("claude", "plan")])
        self.assertFinding(ERROR, "install conflict at ~/.claude/skills/plan: local content differs")


class RepositoryContentChecksTest(DoctorTestCase):
    def test_forbidden_files(self):
        for name in (".env", ".env.local", "default.rules", "auth.json", "state.sqlite", "run.log"):
            self.write(self.repo / "codex" / name, "x")
        self.write(self.repo / ".env.example", "KEY=")
        messages = self.findings(ERROR)
        for name in (".env", ".env.local", "default.rules", "auth.json", "state.sqlite", "run.log"):
            self.assertIn(f"codex/{name}: forbidden file in the repository", messages)
        self.assertFalse(any(".env.example" in message for message in messages))

    def test_secret_patterns(self):
        self.write(self.repo / "docs/notes.md", f"line one\ntoken {FAKE_API_KEY}\n")
        self.assertFinding(ERROR, "docs/notes.md:2: possible API key")

    def test_home_paths_in_owner_folders_only(self):
        self.write(self.repo / "shared/instructions.md", "Run /Users/someone/bin/tool\n")
        self.write(self.repo / "docs/notes.md", "Run /Users/someone/bin/tool\n")
        self.assertEqual(
            [m for m in self.findings(ERROR) if "home path" in m],
            ["shared/instructions.md:1: absolute home path /Users/someone"],
        )

    def test_placeholders_and_home_relative_paths_are_allowed(self):
        self.write(self.repo / "shared/instructions.md", "See /Users/<name>, ~/.claude/skills and $HOME/bin\n")
        self.assertEqual(self.findings(), [])

    def test_git_and_pycache_are_skipped(self):
        self.write(self.repo / ".git/config", FAKE_API_KEY)
        self.write(self.repo / "scripts/__pycache__/x.log", "x")
        self.assertEqual(self.findings(), [])
