import unittest
from pathlib import Path

from ai_config.paths import Environment


class EnvironmentTest(unittest.TestCase):
    def test_defaults_follow_home(self):
        env = Environment.from_env({"HOME": "/h"})
        self.assertEqual(env.codex_home, Path("/h/.codex"))
        self.assertEqual(env.state_dir, Path("/h/.local/state/ai-config"))
        self.assertEqual(env.codex_skills, Path("/h/.agents/skills"))
        self.assertEqual(env.codex_legacy_skills, Path("/h/.codex/skills"))
        self.assertEqual(env.claude_skills, Path("/h/.claude/skills"))

    def test_codex_home_and_state_home_overrides(self):
        env = Environment.from_env({"HOME": "/h", "CODEX_HOME": "/c", "XDG_STATE_HOME": "/s"})
        self.assertEqual(env.codex_legacy_skills, Path("/c/skills"))
        self.assertEqual(env.state_dir, Path("/s/ai-config"))

    def test_expand_and_shorten(self):
        env = Environment.from_env({"HOME": "/h"})
        self.assertEqual(env.expand("~/.claude/skills/x"), Path("/h/.claude/skills/x"))
        self.assertEqual(env.shorten(Path("/h/.claude/skills/x")), "~/.claude/skills/x")
        self.assertEqual(env.shorten(Path("/elsewhere")), "/elsewhere")

    def test_expand_rejects_paths_outside_home(self):
        env = Environment.from_env({"HOME": "/h"})
        for target in ("/h/.claude", "~//tmp/x", "~/", "~/.", "~/a/../../etc"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                env.expand(target)

    def test_codex_targets_follow_codex_home(self):
        env = Environment.from_env({"HOME": "/h", "CODEX_HOME": "/c"})
        self.assertEqual(env.expand("~/.codex/AGENTS.md"), Path("/c/AGENTS.md"))
        self.assertEqual(env.expand("~/.agents/skills/x"), Path("/h/.agents/skills/x"))
        self.assertEqual(env.shorten(Path("/c/skills/x")), "$CODEX_HOME/skills/x")
