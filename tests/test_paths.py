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

    def test_expand_rejects_other_paths(self):
        env = Environment.from_env({"HOME": "/h"})
        with self.assertRaises(ValueError):
            env.expand("/h/.claude")
