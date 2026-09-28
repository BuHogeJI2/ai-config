import json
import os
import shutil
import unittest
from unittest import mock

from ai_config.manifest import parse_manifest
from ai_config.paths import Environment
from ai_config.runtime_checks import (
    McpInventory,
    check_commands,
    check_mcp,
    check_skill_files,
    claude_mcp_inventory,
    codex_mcp_inventory,
)
from tests.helpers import FakeWorldTestCase, skill_entry


def entry(owner="shared", **requires):
    raw = skill_entry(owner, "plan")
    raw["requires"] = requires
    return parse_manifest({"version": 1, "entries": [raw]}).entries[0]


class CommandTest(unittest.TestCase):
    def test_missing_commands_are_errors(self):
        problems = check_commands(entry(commands=["node", "nope"]), which=lambda name: "/bin/x" if name == "node" else None)
        self.assertEqual([p.message for p in problems], ["entry 'skill/plan': required command 'nope' is not on PATH"])
        self.assertEqual(problems[0].level, "error")


class CodexMcpInventoryTest(FakeWorldTestCase):
    def inventory(self, text):
        self.write(self.env.codex_home / "config.toml", text)
        return codex_mcp_inventory(self.env)

    def test_plain_headers_comments_and_unrelated_sections(self):
        inventory = self.inventory(
            "# [mcp_servers.commented]\n"
            "model = 'x'\n"
            "[mcp_servers.docs]\n"
            "command = 'docs'\n"
            "[mcp_servers.docs.env]\n"
            "TOKEN = 'secret'\n"
            "[ mcp_servers.github ]  # trailing comment\n"
            "[projects.\"/tmp/mcp_servers\"]\n"
            "note = 'mcp_servers'\n"
        )
        self.assertEqual(inventory.names, {"docs", "github"})
        self.assertIsNone(inventory.unsure)

    def test_only_understood_syntax_gives_missing(self):
        inventory = self.inventory("[mcp_servers.docs]\ncommand = 'docs'\n[profiles.fast]\nmodel = 'x'\n")
        self.assertIsNone(inventory.unsure)
        self.assertEqual(inventory.status("docs"), None)
        self.assertEqual(inventory.status("github"), "missing")

    def test_quoted_names_and_inline_tables_are_unknown(self):
        for text in (
            '[mcp_servers."my server"]\n',
            "mcp_servers = { docs = { command = 'x' } }\n",
            "[mcp_servers]\ndocs = {}\n",
            "mcp_servers.docs.command = 'x'\n",
            '["mcp_servers".docs]\n',
            "[[mcp_servers.docs]]\n",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.inventory(text).status("docs"), "unknown")

    def test_unsupported_lines_are_reported_without_their_values(self):
        inventory = self.inventory('model = "x"\nmcp_servers.docs.env = { TOKEN = "SYNTHETIC-TOKEN-123456" }\n')
        self.assertEqual(inventory.status("docs"), "unknown")
        self.assertNotIn("SYNTHETIC", inventory.unsure)
        self.assertIn("line 2", inventory.unsure)

    def test_headers_inside_multiline_strings_are_ignored(self):
        for quote in ('"""', "'''"):
            with self.subTest(quote=quote):
                inventory = self.inventory(
                    f"developer_instructions = {quote}\nUse this:\n[mcp_servers.docs]\n{quote}\n[mcp_servers.real]\n"
                )
                self.assertEqual(inventory.names, {"real"})
                self.assertEqual(inventory.status("docs"), "missing")

    def test_comments_single_line_strings_and_escapes_do_not_confuse_headers(self):
        cases = (
            ('# Example delimiter: """\n[mcp_servers.docs]\n', {"docs"}),
            ("note = '\"\"\"'\n[mcp_servers.docs]\n", {"docs"}),
            ('note = "a \\"\\"\\" b"\n[mcp_servers.docs]\n', {"docs"}),
            ("note = '''one line'''\n[mcp_servers.docs]\n", {"docs"}),
            ('text = """\nescaped \\"""\n[mcp_servers.docs]\n"""\n', set()),
            ('text = """ends with quotes""""\n[mcp_servers.docs]\n', {"docs"}),
        )
        for text, names in cases:
            with self.subTest(text=text):
                inventory = self.inventory(text)
                self.assertEqual(inventory.names, names)
                self.assertIsNone(inventory.unsure)

    def test_unclosed_single_line_string_is_unknown(self):
        inventory = self.inventory('note = "never closed\n[mcp_servers.other]\n')
        self.assertEqual(inventory.status("docs"), "unknown")
        self.assertIn("line 1", inventory.unsure)

    def test_codex_home_and_missing_file(self):
        self.assertEqual(codex_mcp_inventory(self.env).status("docs"), "missing")
        env = Environment.from_env({"HOME": str(self.home), "CODEX_HOME": str(self.home / "custom")})
        self.write(self.home / "custom/config.toml", "[mcp_servers.docs]\n")
        self.assertEqual(codex_mcp_inventory(env).names, {"docs"})


class ClaudeMcpInventoryTest(FakeWorldTestCase):
    def test_reads_user_scope_keys(self):
        self.write(self.home / ".claude.json", json.dumps({"mcpServers": {"docs": {"env": {"TOKEN": "x"}}}, "projects": {}}))
        self.assertEqual(claude_mcp_inventory(self.env).names, {"docs"})

    def test_invalid_file_is_unknown_and_missing_file_is_missing(self):
        self.assertEqual(claude_mcp_inventory(self.env).status("docs"), "missing")
        self.write(self.home / ".claude.json", "{")
        self.assertEqual(claude_mcp_inventory(self.env).status("docs"), "unknown")


class CheckMcpTest(unittest.TestCase):
    def test_checks_only_the_agents_the_entry_targets(self):
        inventories = {"codex": McpInventory(names={"docs"}), "claude": McpInventory(unsure="bad file")}
        self.assertEqual([p.level for p in check_mcp(entry("shared", mcp=["docs"]), inventories)], ["warning"])
        self.assertEqual(check_mcp(entry("codex", mcp=["docs"]), inventories), [])
        inventories["codex"] = McpInventory()
        problems = check_mcp(entry("codex", mcp=["docs"]), inventories)
        self.assertEqual([p.message for p in problems], ["entry 'skill/plan': codex MCP server 'docs' is not configured"])


class SkillFilesTest(FakeWorldTestCase):
    def messages(self, skill):
        return [problem.message for problem in check_skill_files(skill, "shared/skills/plan")]

    def test_clean_skill(self):
        skill = self.add_skill(self.repo, "plan")
        self.write(skill / "scripts/run.sh", "#!/bin/bash\necho ok\n").chmod(0o755)
        self.write(skill / "scripts/tool.py", "print('ok')\n")
        self.write(skill / "SKILL.md", "---\nname: plan\ndescription: d\n---\nSee [ref](reference.md#top), [web](https://x.y), [anchor](#a).\n")
        self.write(skill / "reference.md", "x")
        self.assertEqual(self.messages(skill), [])

    def test_shebang_without_executable_bit(self):
        skill = self.add_skill(self.repo, "plan")
        self.write(skill / "run.sh", "#!/bin/sh\necho ok\n").chmod(0o644)
        (problem,) = check_skill_files(skill, "shared/skills/plan")
        self.assertEqual(problem.level, "warning")
        self.assertTrue(problem.message.startswith("shared/skills/plan/run.sh: has a shebang but is not executable"))

    def test_syntax_errors(self):
        skill = self.add_skill(self.repo, "plan")
        self.write(skill / "bad.py", "def broken(:\n")
        self.write(skill / "bad.sh", "if then fi (\n")
        messages = self.messages(skill)
        self.assertTrue(any(m.startswith("shared/skills/plan/bad.py: Python syntax error") for m in messages), messages)
        self.assertTrue(any(m.startswith("shared/skills/plan/bad.sh: syntax error") for m in messages), messages)
        self.assertFalse((skill / "__pycache__").exists())

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_node_syntax_error(self):
        skill = self.add_skill(self.repo, "plan")
        self.write(skill / "bad.mjs", "export const = ;\n")
        self.assertTrue(any(m.startswith("shared/skills/plan/bad.mjs: syntax error") for m in self.messages(skill)))

    def test_markdown_link_forms(self):
        skill = self.add_skill(self.repo, "plan")
        for name in ("file name.md", "x(1).md", "f(1).md"):
            self.write(skill / name, "x")
        self.write(
            skill / "SKILL.md",
            "---\nname: plan\ndescription: d\n---\n"
            "[a](file%20name.md) [b](<file name.md>) [c](x\\(1\\).md) [d](f(1).md \"title\") "
            "[e](HTTPS://example.invalid/) [f](Mailto:x@y.z) [g](file%20name.md?x=1#top)\n",
        )
        self.assertEqual(self.messages(skill), [])

    def test_unreadable_entries_become_findings(self):
        skill = self.add_skill(self.repo, "plan")
        (skill / "locked").mkdir()
        self.write(skill / "locked/run.sh", "echo\n")
        (skill / "locked").chmod(0)
        self.addCleanup((skill / "locked").chmod, 0o755)
        (skill / "SKILL.md").chmod(0)
        self.addCleanup((skill / "SKILL.md").chmod, 0o644)
        messages = self.messages(skill)
        self.assertTrue(any("cannot read" in m and "locked" in m for m in messages), messages)
        self.assertTrue(any(m.startswith("shared/skills/plan/SKILL.md: cannot read") for m in messages), messages)

    def test_non_utf8_syntax_error_output_is_decoded(self):
        skill = self.add_skill(self.repo, "plan")
        (skill / "bad.sh").write_bytes(b"echo (\xff\n")
        self.assertTrue(any(m.startswith("shared/skills/plan/bad.sh: syntax error") for m in self.messages(skill)))

    def test_startup_hooks_do_not_run_during_syntax_checks(self):
        sentinel = self.home / "sentinel"
        preload = self.write(self.home / "preload.cjs", f"require('fs').writeFileSync({json.dumps(str(sentinel))}, 'ran')\n")
        bash_env = self.write(self.home / "bash_env.sh", f"echo ran > {sentinel}\n")
        skill = self.add_skill(self.repo, "plan")
        self.write(skill / "ok.sh", "echo ok\n")
        self.write(skill / "ok.mjs", "export const x = 1;\n")
        hooks = {"NODE_OPTIONS": f"--require={preload}", "BASH_ENV": str(bash_env), "ENV": str(bash_env)}
        with mock.patch.dict(os.environ, hooks):
            self.assertEqual(self.messages(skill), [])
        self.assertFalse(sentinel.exists())

    def test_missing_linked_file(self):
        skill = self.add_skill(self.repo, "plan")
        self.write(skill / "SKILL.md", "---\nname: plan\ndescription: d\n---\nRead [the template](templates/missing.md).\n")
        self.assertEqual(
            self.messages(skill), ["shared/skills/plan/SKILL.md:5: linked file does not exist: templates/missing.md"]
        )
