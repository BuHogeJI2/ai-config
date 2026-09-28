import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ai_config.manifest import ManifestError, load_manifest, parse_manifest, skill_targets


def skill_entry(**overrides):
    entry = {
        "id": "skill/plan",
        "method": "symlink",
        "source": "claude/skills/plan",
        "targets": ["~/.claude/skills/plan"],
    }
    entry.update(overrides)
    return entry


def manifest(*entries, **top):
    data = {"version": 1, "external": [], "entries": list(entries)}
    data.update(top)
    return data


class ParseManifestTest(unittest.TestCase):
    def assertProblem(self, data, fragment):
        with self.assertRaises(ManifestError) as caught:
            parse_manifest(data)
        self.assertTrue(
            any(fragment in problem for problem in caught.exception.problems),
            f"{fragment!r} not in {caught.exception.problems}",
        )

    def test_valid_manifest(self):
        compose = {
            "id": "instructions/codex",
            "method": "compose",
            "sources": ["shared/instructions.md", "codex/instructions.md"],
            "targets": ["~/.codex/AGENTS.md"],
        }
        parsed = parse_manifest(
            manifest(skill_entry(requires={"commands": ["node"]}), compose, external=["agterm"])
        )
        self.assertEqual(parsed.external, ("agterm",))
        self.assertEqual(parsed.entries[0].sources, ("claude/skills/plan",))
        self.assertEqual(parsed.entries[0].requires, {"commands": ("node",)})
        self.assertEqual(parsed.entries[1].sources, ("shared/instructions.md", "codex/instructions.md"))
        self.assertIs(parsed.entry_for_source("codex/instructions.md"), parsed.entries[1])
        self.assertTrue(parsed.is_external("AGTERM"))

    def test_version_must_be_1(self):
        self.assertProblem(manifest(version=2), "version must be 1")

    def test_unknown_keys(self):
        self.assertProblem(manifest(extra=True), "unknown manifest keys: extra")
        self.assertProblem(manifest(skill_entry(target="~/x")), "unknown keys: target")

    def test_unknown_method(self):
        self.assertProblem(manifest(skill_entry(method="copy")), "'method' must be one of")

    def test_symlink_needs_source(self):
        entry = skill_entry()
        del entry["source"]
        self.assertProblem(manifest(entry), "symlink entries need a 'source'")

    def test_source_and_sources_together(self):
        self.assertProblem(manifest(skill_entry(sources=["a"])), "either 'source' or 'sources'")

    def test_source_must_be_a_normalized_path_inside_repository(self):
        for source in ("../outside", "/abs", ".", "claude/./skills/plan", "claude//skills/plan", "claude/skills/plan/"):
            with self.subTest(source=source):
                self.assertProblem(manifest(skill_entry(source=source)), "relative path inside the repository")

    def test_only_supported_target_shapes(self):
        for target in (
            "~/.agents/skills/plan",
            "~/.claude/skills/plan",
            "~/.claude/CLAUDE.md",
            "~/.claude/rules/shared.md",
            "~/.codex/AGENTS.md",
        ):
            with self.subTest(target=target):
                parse_manifest(manifest(skill_entry(targets=[target])))
        for target in (
            "/Users/x/.claude/skills/plan",
            "~//tmp/x",
            "~/.claude/skills/../settings.json",
            "~/.claude/skills/.hidden",
            "~/.claude/skills/a/b",
            "~/.claude/settings.json",
            "~/.claude",
            "~/.codex/config.toml",
            "~/.codex/rules/default.rules",
            "~/.claude/rules/notes.txt",
            "~/.claudeXskills/plan",
        ):
            with self.subTest(target=target):
                self.assertProblem(manifest(skill_entry(targets=[target])), "unsupported target")

    def test_synced_and_external_skill_targets_are_protected(self):
        self.assertProblem(
            manifest(skill_entry(targets=["~/.claude/skills/Synced"])), "is reserved for cloud-synced skills"
        )
        self.assertProblem(
            manifest(skill_entry(targets=["~/.agents/skills/AGTERM"]), external=["agterm"]),
            "is an external skill and is app-managed",
        )
        parse_manifest(manifest(skill_entry(targets=["~/.claude/rules/agterm.md"]), external=["agterm"]))

    def test_duplicate_ids_and_targets_ignore_case(self):
        self.assertProblem(
            manifest(skill_entry(), skill_entry(id="SKILL/PLAN", targets=["~/.claude/skills/other"])), "duplicate entry id"
        )
        self.assertProblem(
            manifest(skill_entry(), skill_entry(id="other", targets=["~/.claude/skills/PLAN"])), "duplicate target"
        )

    def test_requires_lists(self):
        self.assertProblem(manifest(skill_entry(requires={"commands": "node"})), "'requires.commands' must be a list")
        self.assertProblem(manifest(skill_entry(requires={"apps": []})), "unknown 'requires' keys: apps")


class LoadManifestTest(unittest.TestCase):
    def test_missing_file(self):
        with TemporaryDirectory() as temp, self.assertRaises(ManifestError) as caught:
            load_manifest(Path(temp) / "manifest.json")
        self.assertIn("manifest.json not found", caught.exception.problems[0])

    def test_invalid_json(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(ManifestError) as caught:
                load_manifest(path)
        self.assertIn("not valid JSON", caught.exception.problems[0])


class SkillTargetsTest(unittest.TestCase):
    def test_owner_decides_targets(self):
        self.assertEqual(skill_targets("shared", "x"), ("~/.agents/skills/x", "~/.claude/skills/x"))
        self.assertEqual(skill_targets("codex", "x"), ("~/.agents/skills/x",))
        self.assertEqual(skill_targets("claude", "x"), ("~/.claude/skills/x",))
