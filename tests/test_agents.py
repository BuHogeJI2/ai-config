import unittest

from ai_config.agents import (
    AGENTS,
    DEFAULT,
    SAVED,
    TEMPORARY,
    AgentsError,
    effective_agents,
    parse_agents,
    target_agent,
)


class TargetAgentTest(unittest.TestCase):
    def test_agent_comes_from_the_unexpanded_target(self):
        self.assertEqual(target_agent("~/.claude/skills/a"), "claude")
        self.assertEqual(target_agent("~/.claude/CLAUDE.md"), "claude")
        self.assertEqual(target_agent("~/.agents/skills/a"), "codex")
        self.assertEqual(target_agent("~/.codex/AGENTS.md"), "codex")

    def test_unknown_target_is_an_error(self):
        for target in ("~/.config/a", "/Users/someone/.claude/skills/a", "~/.claudex/a"):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    target_agent(target)


class ParseAgentsTest(unittest.TestCase):
    def test_result_is_in_canonical_order(self):
        self.assertEqual(parse_agents("codex"), ("codex",))
        self.assertEqual(parse_agents("claude"), ("claude",))
        self.assertEqual(parse_agents("claude,codex"), ("codex", "claude"))
        self.assertEqual(parse_agents(" codex , claude "), ("codex", "claude"))

    def test_invalid_values_are_errors(self):
        for value in ("", ",", "codex,", "codex,,claude", "gemini", "codex,codex", "Codex"):
            with self.subTest(value=value):
                with self.assertRaises(AgentsError):
                    parse_agents(value)


class EffectiveAgentsTest(unittest.TestCase):
    def test_flag_then_saved_then_both(self):
        self.assertEqual(effective_agents(("claude",), ("codex",)), (("claude",), TEMPORARY))
        self.assertEqual(effective_agents(None, ("codex",)), (("codex",), SAVED))
        self.assertEqual(effective_agents(None, None), (AGENTS, DEFAULT))
