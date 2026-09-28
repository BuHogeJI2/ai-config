import io
import json
import os
import stat
from pathlib import Path

import ai_config.adopt as adopt_module
from ai_config.adopt import AdoptError, adopt
from ai_config.fileops import TargetChangedError
from ai_config.cli import main
from ai_config.manifest import load_manifest
from ai_config.paths import Environment
from ai_config.trees import identical
from tests.helpers import FakeWorldTestCase, skill_entry

FAKE_API_KEY = "sk-" + "a1B2" * 8


class AdoptTest(FakeWorldTestCase):
    def local_skill(self, folder, name="plan", **kwargs):
        skill = self.add_skill(folder, name, **kwargs)
        self.write(skill / "scripts/run.sh", "echo\n").chmod(0o755)
        os.symlink("SKILL.md", skill / "alias.md")
        self.write(skill / ".DS_Store", "finder")
        return skill

    def entries(self):
        return json.loads((self.repo / "manifest.json").read_text())["entries"]

    def test_each_owner_gets_its_folder_and_targets(self):
        cases = (
            ("claude", "claude", ["~/.claude/skills/plan"]),
            ("codex", "codex", ["~/.agents/skills/plan"]),
            ("claude", "shared", ["~/.agents/skills/plan", "~/.claude/skills/plan"]),
        )
        for agent, owner, targets in cases:
            with self.subTest(agent=agent, owner=owner):
                self.setUp()
                folder = self.env.claude_skills if agent == "claude" else self.env.codex_legacy_skills
                local = self.local_skill(folder)
                before = sorted(p.name for p in folder.iterdir())

                result = adopt(self.repo, self.env, agent, "plan", owner)

                copied = self.repo / owner / "skills/plan"
                self.assertEqual(result.source, f"{owner}/skills/plan")
                self.assertTrue(result.entry_added)
                self.assertTrue(identical(local, copied))
                self.assertFalse((copied / ".DS_Store").exists())
                self.assertTrue(stat.S_IMODE((copied / "scripts/run.sh").stat().st_mode) & 0o100)
                self.assertEqual(os.readlink(copied / "alias.md"), "SKILL.md")
                self.assertEqual(
                    self.entries(), [{"id": "skill/plan", "method": "symlink", "source": result.source, "targets": targets}]
                )
                self.assertEqual(sorted(p.name for p in folder.iterdir()), before)
                load_manifest(self.repo / "manifest.json")

    def test_codex_skill_is_found_in_either_location(self):
        self.local_skill(self.env.codex_skills)
        self.assertEqual(adopt(self.repo, self.env, "codex", "plan", "codex").local, self.env.codex_skills / "plan")

    def test_two_different_codex_copies_are_refused(self):
        self.local_skill(self.env.codex_skills)
        self.local_skill(self.env.codex_legacy_skills, description="Other.")
        with self.assertRaisesRegex(AdoptError, "differ"):
            adopt(self.repo, self.env, "codex", "plan", "codex")

    def test_two_identical_codex_copies_are_accepted(self):
        self.local_skill(self.env.codex_skills)
        self.local_skill(self.env.codex_legacy_skills)
        adopt(self.repo, self.env, "codex", "plan", "codex")

    def test_owner_must_match_agent_or_be_shared(self):
        self.local_skill(self.env.claude_skills)
        with self.assertRaisesRegex(AdoptError, "into 'claude' or 'shared'"):
            adopt(self.repo, self.env, "claude", "plan", "codex")

    def test_refuses_external_names(self):
        self.write_manifest(external=["agterm"])
        self.local_skill(self.env.claude_skills, "agterm")
        with self.assertRaisesRegex(AdoptError, "external"):
            adopt(self.repo, self.env, "claude", "agterm", "claude")

    def test_refuses_secrets_forbidden_files_and_home_paths(self):
        for extra, message in (
            (("notes.md", f"key {FAKE_API_KEY}\n"), "possible API key"),
            ((".env", "A=1\n"), "forbidden file"),
            (("notes.md", "see /Users/someone/x\n"), "absolute home path"),
        ):
            with self.subTest(message=message):
                self.setUp()
                local = self.local_skill(self.env.claude_skills)
                self.write(local / extra[0], extra[1])
                with self.assertRaisesRegex(AdoptError, message):
                    adopt(self.repo, self.env, "claude", "plan", "claude")
                self.assertFalse((self.repo / "claude").exists())
                self.assertEqual(self.entries(), [])

    def test_refuses_links_leaving_the_skill(self):
        local = self.local_skill(self.env.claude_skills)
        os.symlink("../other", local / "escape")
        with self.assertRaisesRegex(AdoptError, "links outside the skill folder"):
            adopt(self.repo, self.env, "claude", "plan", "claude")

    def test_refuses_links_and_missing_skills(self):
        with self.assertRaisesRegex(AdoptError, "no local claude skill"):
            adopt(self.repo, self.env, "claude", "plan", "claude")
        source = self.add_skill(self.repo / "claude/skills", "plan")
        self.write_manifest([skill_entry("claude", "plan")])
        self.link(self.env.claude_skills / "plan", source)
        with self.assertRaisesRegex(AdoptError, "already a link into this repository"):
            adopt(self.repo, self.env, "claude", "plan", "claude")
        self.link(self.env.claude_skills / "other", self.home / "elsewhere")
        with self.assertRaisesRegex(AdoptError, "is a link"):
            adopt(self.repo, self.env, "claude", "other", "claude")

    def test_existing_repository_copy_needs_replace_repo(self):
        self.add_skill(self.repo / "claude/skills", "plan", description="Repository version.")
        self.write_manifest([skill_entry("claude", "plan")])
        local = self.local_skill(self.env.claude_skills)
        with self.assertRaisesRegex(AdoptError, "--replace-repo"):
            adopt(self.repo, self.env, "claude", "plan", "claude")

        result = adopt(self.repo, self.env, "claude", "plan", "claude", replace_repo=True)

        self.assertTrue(result.replaced_repo_copy)
        self.assertFalse(result.entry_added)
        self.assertTrue(identical(local, self.repo / "claude/skills/plan"))
        self.assertEqual(len(self.entries()), 1)

    def test_same_name_under_another_owner_is_refused(self):
        self.add_skill(self.repo / "claude/skills", "plan")
        self.write_manifest([skill_entry("claude", "plan")])
        self.local_skill(self.env.claude_skills)
        with self.assertRaisesRegex(AdoptError, "duplicate target: ~/.claude/skills/plan"):
            adopt(self.repo, self.env, "claude", "plan", "shared", replace_repo=True)
        self.assertFalse((self.repo / "shared").exists())

    def test_owner_folder_resolving_outside_repository_is_refused(self):
        self.local_skill(self.env.claude_skills)
        (self.home / "outside").mkdir()
        (self.repo / "claude").mkdir()
        os.symlink(self.home / "outside", self.repo / "claude/skills")
        with self.assertRaisesRegex(AdoptError, "outside the repository"):
            adopt(self.repo, self.env, "claude", "plan", "claude")

    def test_legacy_alias_of_install_folder_is_searched_once(self):
        self.env = Environment.from_env({"HOME": str(self.home), "CODEX_HOME": str(self.home / ".agents")})
        self.local_skill(self.env.codex_skills)
        adopt(self.repo, self.env, "codex", "plan", "codex")

    def test_manifest_keeps_existing_keys_and_entry_order(self):
        self.add_skill(self.repo / "claude/skills", "first")
        self.write_manifest([skill_entry("claude", "first")], external=["agterm"])
        self.local_skill(self.env.claude_skills)
        adopt(self.repo, self.env, "claude", "plan", "claude")
        data = json.loads((self.repo / "manifest.json").read_text())
        self.assertEqual(data["external"], ["agterm"])
        self.assertEqual([entry["id"] for entry in data["entries"]], ["skill/first", "skill/plan"])
        self.assertTrue((self.repo / "manifest.json").read_text().endswith("}\n"))


class AdoptSafetyTest(FakeWorldTestCase):
    def setUp(self):
        super().setUp()
        self.local = self.add_skill(self.env.claude_skills, "plan")

    def patch_copytree(self, before=None, after=None):
        original = adopt_module.shutil.copytree

        def copytree(source, destination, **kwargs):
            if before:
                before(source, destination)
            result = original(source, destination, **kwargs)
            if after:
                after(source, destination)
            return result

        adopt_module.shutil.copytree = copytree
        self.addCleanup(setattr, adopt_module.shutil, "copytree", original)

    def entries(self):
        return json.loads((self.repo / "manifest.json").read_text())["entries"]

    def assertRepositoryUntouched(self, manifest_text=None):
        self.assertFalse((self.repo / "claude/skills/plan").exists())
        self.assertEqual([p.name for p in (self.repo / "claude/skills").iterdir()] if (self.repo / "claude/skills").exists() else [], [])
        if manifest_text is not None:
            self.assertEqual((self.repo / "manifest.json").read_text(), manifest_text)

    def test_secret_added_to_the_local_copy_after_validation_is_refused(self):
        manifest_text = (self.repo / "manifest.json").read_text()
        self.patch_copytree(before=lambda source, _: self.write(Path(source) / "notes.md", f"{FAKE_API_KEY}\n"))
        with self.assertRaises(TargetChangedError):
            adopt(self.repo, self.env, "claude", "plan", "claude")
        self.assertRepositoryUntouched(manifest_text)

    def test_secret_added_to_the_staged_copy_is_refused(self):
        self.patch_copytree(after=lambda _, staged: self.write(Path(staged) / "notes.md", f"{FAKE_API_KEY}\n"))
        with self.assertRaisesRegex(AdoptError, "possible API key"):
            adopt(self.repo, self.env, "claude", "plan", "claude")
        self.assertRepositoryUntouched()

    def test_destination_created_during_copy_is_kept(self):
        self.patch_copytree(after=lambda *_: self.write(self.repo / "claude/skills/plan/SKILL.md", "someone else\n"))
        with self.assertRaises(TargetChangedError):
            adopt(self.repo, self.env, "claude", "plan", "claude")
        self.assertEqual((self.repo / "claude/skills/plan/SKILL.md").read_text(), "someone else\n")
        self.assertEqual(self.entries(), [])

    def test_owner_folder_redirected_outside_during_copy_writes_nothing_there(self):
        outside = self.home / "outside"
        outside.mkdir()

        def redirect(*_):
            skills = self.repo / "claude/skills"
            os.rename(skills, self.repo / "claude/skills-moved")
            os.symlink(outside, skills)

        self.patch_copytree(after=redirect)
        with self.assertRaises((AdoptError, TargetChangedError)):
            adopt(self.repo, self.env, "claude", "plan", "claude")
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(self.entries(), [])

    def test_manifest_changed_during_copy_is_kept(self):
        self.add_skill(self.repo / "codex/skills", "other")
        concurrent = json.dumps({"version": 1, "external": [], "entries": [skill_entry("codex", "other")]})
        self.patch_copytree(after=lambda *_: self.write(self.repo / "manifest.json", concurrent))
        with self.assertRaises(TargetChangedError):
            adopt(self.repo, self.env, "claude", "plan", "claude")
        self.assertEqual((self.repo / "manifest.json").read_text(), concurrent)
        self.assertFalse((self.repo / "claude/skills/plan").exists())

    def test_manifest_write_failure_rolls_back_the_new_folder(self):
        original = adopt_module.write_text_file

        def fail(*_, **__):
            raise OSError("disk full")

        adopt_module.write_text_file = fail
        self.addCleanup(setattr, adopt_module, "write_text_file", original)
        manifest_text = (self.repo / "manifest.json").read_text()
        with self.assertRaisesRegex(AdoptError, "rolled back"):
            adopt(self.repo, self.env, "claude", "plan", "claude")
        self.assertRepositoryUntouched(manifest_text)

    def patch_manifest_writer(self, wrapper):
        original = adopt_module.write_text_file
        adopt_module.write_text_file = wrapper(original)
        self.addCleanup(setattr, adopt_module, "write_text_file", original)

    def test_rollback_after_a_redirected_owner_folder_touches_nothing(self):
        foreign = self.add_skill(self.home / "outside", "plan")

        def redirect_then_fail(original):
            def write(*_, **__):
                os.rename(self.repo / "claude/skills", self.repo / "claude/skills-moved")
                os.symlink(self.home / "outside", self.repo / "claude/skills")
                raise OSError("disk full")
            return write

        self.patch_manifest_writer(redirect_then_fail)
        with self.assertRaisesRegex(AdoptError, "nothing was rolled back"):
            adopt(self.repo, self.env, "claude", "plan", "claude")
        self.assertTrue((foreign / "SKILL.md").is_file())
        self.assertTrue((self.repo / "claude/skills-moved/plan/SKILL.md").is_file())
        self.assertEqual(self.entries(), [])

    def test_manifest_edited_right_before_replacement_is_kept(self):
        concurrent = json.dumps({"version": 1, "external": ["concurrent"], "entries": []})

        def edit_before_replace(original):
            def write(path, text, unchanged):
                def edited_then_check():
                    self.write(self.repo / "manifest.json", concurrent)
                    return unchanged()
                return original(path, text, unchanged=edited_then_check)
            return write

        self.patch_manifest_writer(edit_before_replace)
        with self.assertRaises(TargetChangedError):
            adopt(self.repo, self.env, "claude", "plan", "claude")
        self.assertEqual((self.repo / "manifest.json").read_text(), concurrent)
        self.assertFalse((self.repo / "claude/skills/plan").exists())
        self.assertEqual([p.name for p in self.repo.iterdir() if p.name.startswith(".manifest.json")], [])

    def test_failure_while_replacing_restores_the_previous_repository_copy(self):
        previous = self.add_skill(self.repo / "claude/skills", "plan", description="Repository version.")
        self.write_manifest([skill_entry("claude", "plan")])
        before = (previous / "SKILL.md").read_text()
        original_rename = adopt_module.os.rename
        calls = []

        def rename(source, destination):
            calls.append(destination)
            if len(calls) == 2:
                raise OSError("rename failed")
            return original_rename(source, destination)

        adopt_module.os.rename = rename
        self.addCleanup(setattr, adopt_module.os, "rename", original_rename)
        with self.assertRaises(AdoptError):
            adopt(self.repo, self.env, "claude", "plan", "claude", replace_repo=True)
        adopt_module.os.rename = original_rename
        self.assertEqual((previous / "SKILL.md").read_text(), before)
        self.assertEqual(sorted(p.name for p in (self.repo / "claude/skills").iterdir()), ["plan"])

    def test_copy_failure_leaves_no_staged_folder(self):
        def fail(*_):
            raise OSError("copy failed")

        self.patch_copytree(before=fail)
        with self.assertRaises(AdoptError):
            adopt(self.repo, self.env, "claude", "plan", "claude")
        self.assertRepositoryUntouched()

    def test_link_chains_and_loops_leaving_the_skill_are_refused(self):
        os.symlink(".", self.local / "back")
        os.symlink("back/../outside", self.local / "escape")
        with self.assertRaisesRegex(AdoptError, "links outside the skill folder"):
            adopt(self.repo, self.env, "claude", "plan", "claude")
        os.remove(self.local / "escape")
        os.remove(self.local / "back")
        os.symlink("loop-b", self.local / "loop-a")
        os.symlink("loop-a", self.local / "loop-b")
        with self.assertRaisesRegex(AdoptError, "link loop"):
            adopt(self.repo, self.env, "claude", "plan", "claude")

    def test_prospective_manifest_is_validated_before_copying(self):
        self.add_skill(self.env.codex_skills, "synced")
        with self.assertRaisesRegex(AdoptError, "reserved for cloud-synced skills"):
            adopt(self.repo, self.env, "codex", "synced", "shared")
        self.assertFalse((self.repo / "shared").exists())

    def test_reused_entry_must_match_method_and_source(self):
        self.add_skill(self.repo / "claude/skills", "plan")
        entry = skill_entry("claude", "plan")
        entry["method"] = "compose"
        entry["sources"] = [entry.pop("source"), "claude/CLAUDE.md"]
        self.write_manifest([entry])
        with self.assertRaisesRegex(AdoptError, "does not match claude/skills/plan"):
            adopt(self.repo, self.env, "claude", "plan", "claude", replace_repo=True)

    def test_agent_specific_versions_of_one_name_can_coexist(self):
        self.add_skill(self.env.codex_legacy_skills, "plan", description="Codex version.")
        first = adopt(self.repo, self.env, "codex", "plan", "codex")
        second = adopt(self.repo, self.env, "claude", "plan", "claude")
        self.assertEqual((first.entry_id, second.entry_id), ("skill/plan", "skill/claude/plan"))
        load_manifest(self.repo / "manifest.json")


class AdoptCommandTest(FakeWorldTestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        code = main(list(argv), environ={"HOME": str(self.home)}, repo_root=self.repo, out=out)
        return code, out.getvalue().splitlines()

    def test_adopt_then_install_links_the_skill(self):
        self.add_skill(self.env.codex_legacy_skills, "task-plan")
        code, lines = self.run_cli("adopt", "--agent", "codex", "--skill", "task-plan", "--to", "codex")
        self.assertEqual(code, 0)
        self.assertEqual(
            lines,
            [
                "copied         ~/.codex/skills/task-plan -> codex/skills/task-plan",
                "manifest       added entry skill/task-plan",
                "Nothing was installed or committed. Next: review with git diff, then ai-config install --dry-run.",
            ],
        )
        self.assertFalse(os.path.lexists(self.env.codex_skills / "task-plan"))

        self.assertEqual(self.run_cli("install")[0], 0)
        self.assertEqual(os.readlink(self.env.codex_skills / "task-plan"), str(self.repo.resolve() / "codex/skills/task-plan"))
        self.assertFalse(os.path.lexists(self.env.codex_legacy_skills / "task-plan"))
        self.assertEqual(self.run_cli("doctor")[1][-1], "0 error(s), 0 warning(s)")

    def test_errors_exit_one(self):
        self.assertEqual(
            self.run_cli("adopt", "--agent", "claude", "--skill", "plan", "--to", "claude"),
            (1, ["error    no local claude skill 'plan' in ~/.claude/skills/plan"]),
        )
