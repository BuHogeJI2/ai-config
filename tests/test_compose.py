import hashlib
import io
import json
import os
import stat

import ai_config.installer as installer
import ai_config.planner as planner_module
import ai_config.uninstall as uninstall_module
from ai_config.cli import main
from ai_config.compose import ComposeError, compose, marker
from ai_config.planner import CONFLICT, CREATE, KEEP, PRUNE, REGENERATE, REPLACE
from ai_config.state import StateError, load_state
from tests.helpers import FakeWorldTestCase, skill_entry

SOURCES = ("shared/instructions.md", "codex/instructions.md")
AGENTS_ENTRY = {"id": "instructions/codex", "method": "compose", "sources": list(SOURCES), "targets": ["~/.codex/AGENTS.md"]}


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


class ComposeTest(FakeWorldTestCase):
    def test_joins_sources_below_a_marker(self):
        self.write(self.repo / "shared/instructions.md", "\n\nShared rule.\n\n\n")
        self.write(self.repo / "codex/instructions.md", "Codex rule.")
        composition = compose(self.repo, SOURCES)
        self.assertEqual(composition.body, "Shared rule.\n\nCodex rule.\n")
        self.assertEqual(composition.output, f"{marker(SOURCES)}\n\nShared rule.\n\nCodex rule.\n")
        self.assertEqual(composition.source_hashes["codex/instructions.md"], sha("Codex rule."))

    def test_empty_sources_are_skipped(self):
        self.write(self.repo / "shared/instructions.md", "\n  \n")
        self.write(self.repo / "codex/instructions.md", "Codex rule.\n")
        self.assertEqual(compose(self.repo, SOURCES).body, "Codex rule.\n")
        self.write(self.repo / "codex/instructions.md", "")
        self.assertEqual(compose(self.repo, SOURCES).body, "")

    def test_invalid_sources(self):
        self.write(self.repo / "codex/instructions.md", "x")
        self.write(self.home / "outside.md", "x")
        cases = {
            "missing": lambda: None,
            "link": lambda: os.symlink(self.repo / "codex/instructions.md", self.repo / "shared/instructions.md"),
            "folder": lambda: (self.repo / "shared/instructions.md").mkdir(),
            "not utf-8": lambda: (self.repo / "shared/instructions.md").write_bytes(b"\xff"),
        }
        for name, prepare in cases.items():
            with self.subTest(name=name):
                (self.repo / "shared").mkdir(exist_ok=True)
                path = self.repo / "shared/instructions.md"
                if path.is_symlink() or path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
                prepare()
                with self.assertRaises(ComposeError):
                    compose(self.repo, SOURCES)

    def test_source_folder_resolving_outside_is_refused(self):
        self.write(self.home / "outside/instructions.md", "x")
        self.write(self.repo / "codex/instructions.md", "x")
        os.symlink(self.home / "outside", self.repo / "shared")
        with self.assertRaisesRegex(ComposeError, "outside the repository"):
            compose(self.repo, SOURCES)


class ComposeCycleTestCase(FakeWorldTestCase):
    def setUp(self):
        super().setUp()
        self.target = self.env.codex_home / "AGENTS.md"
        self.write(self.repo / "shared/instructions.md", "Shared rule.\n")
        self.write(self.repo / "codex/instructions.md", "Codex rule.\n")
        self.write_manifest([AGENTS_ENTRY])

    def run_cli(self, *argv):
        out = io.StringIO()
        code = main(list(argv), environ={"HOME": str(self.home)}, repo_root=self.repo, out=out)
        return code, out.getvalue().splitlines()

    def kinds(self, *argv):
        code, lines = self.run_cli("install", "--dry-run", *argv)
        return [line.split()[0] for line in lines if line.split()[0] in (CREATE, KEEP, REPLACE, REGENERATE, PRUNE, CONFLICT, "orphan")]

    def output(self):
        return compose(self.repo, SOURCES).output


class ComposePlanAndInstallTest(ComposeCycleTestCase):
    def test_create_keep_regenerate(self):
        self.assertEqual(self.kinds(), [CREATE])
        self.assertEqual(self.run_cli("install")[0], 0)
        self.assertEqual(self.target.read_text(), self.output())
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o644)
        record = load_state(self.env.state_dir).generated[self.target]
        self.assertEqual((record.output_hash, record.previous_hash), (sha(self.output()), None))
        self.assertEqual(self.kinds(), [KEEP])

        self.write(self.repo / "codex/instructions.md", "Codex rule, changed.\n")
        self.assertEqual(self.kinds(), [REGENERATE])
        code, lines = self.run_cli("doctor")
        self.assertIn("info     install pending (regenerate) at ~/.codex/AGENTS.md", lines)
        self.target.chmod(0o600)
        code, lines = self.run_cli("install")
        self.assertEqual(code, 0)
        self.assertEqual(self.target.read_text(), self.output())
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o600)
        self.assertTrue(any(line.startswith("backup ") for line in lines))

    def test_first_install_replaces_an_existing_file_without_the_marker(self):
        self.write(self.target, "\nShared rule.\n\nCodex rule.\n\n")
        self.assertEqual(self.kinds(), [REPLACE])
        self.assertEqual(self.run_cli("install")[0], 0)
        self.assertEqual(self.target.read_text(), self.output())

    def test_different_existing_file_and_edited_output_are_conflicts(self):
        self.write(self.target, "Hand-written instructions.\n")
        self.assertEqual(self.kinds(), [CONFLICT])
        self.assertEqual(self.kinds("--replace-local", "instructions/codex"), [REPLACE])
        self.run_cli("install", "--replace-local", "instructions/codex")

        self.write(self.target, self.output() + "Local edit.\n")
        code, lines = self.run_cli("install", "--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("was edited since it was generated", lines[0])
        code, lines = self.run_cli("doctor")
        self.assertTrue(any(line.startswith("error    install conflict at ~/.codex/AGENTS.md") for line in lines))

    def test_links_and_folders_at_the_target(self):
        self.link(self.target, self.home / "foreign.md")
        self.assertEqual(self.kinds(), [CONFLICT])
        self.target.unlink()
        self.target.mkdir()
        self.assertEqual(self.kinds(), [CONFLICT])

    def test_source_changed_after_planning_is_not_published(self):
        from ai_config.planner import build_plan
        from ai_config.manifest import load_manifest

        plan = build_plan(self.repo, self.env, load_manifest(self.repo / "manifest.json"), load_state(self.env.state_dir))
        self.write(self.repo / "codex/instructions.md", "Changed after planning.\n")
        with self.assertRaises(installer.TargetChangedError):
            installer.apply_plan(plan, self.repo.resolve(), load_state(self.env.state_dir), self.env.state_dir)
        self.assertFalse(self.target.exists())

    def test_file_created_after_planning_is_not_overwritten(self):
        from ai_config.planner import build_plan
        from ai_config.manifest import load_manifest

        plan = build_plan(self.repo, self.env, load_manifest(self.repo / "manifest.json"), load_state(self.env.state_dir))
        self.write(self.target, "someone else\n")
        with self.assertRaises(installer.TargetChangedError):
            installer.apply_plan(plan, self.repo.resolve(), load_state(self.env.state_dir), self.env.state_dir)
        self.assertEqual(self.target.read_text(), "someone else\n")
        self.assertEqual([p.name for p in self.target.parent.iterdir()], ["AGENTS.md"])


class ComposeInterruptionTest(ComposeCycleTestCase):
    def install_with_failing_save(self, on_call):
        """Run install with the state save number `on_call` failing, then put the real save back."""
        original = installer.save_state
        calls = []

        def save(*args):
            calls.append(1)
            if len(calls) == on_call:
                raise OSError("disk full")
            return original(*args)

        installer.save_state = save
        try:
            with self.assertRaises(OSError):
                self.run_cli("install")
        finally:
            installer.save_state = original

    def test_state_save_failure_after_creating_is_retried_as_keep(self):
        self.install_with_failing_save(on_call=2)
        self.assertEqual(self.target.read_text(), self.output())
        self.assertEqual(self.kinds(), [KEEP])
        self.assertEqual(self.run_cli("install")[0], 0)
        self.assertIsNone(load_state(self.env.state_dir).generated[self.target].previous_hash)

    def test_state_save_failure_after_regenerating_is_retried_as_keep(self):
        self.run_cli("install")
        self.write(self.repo / "codex/instructions.md", "Changed.\n")
        self.install_with_failing_save(on_call=2)
        record = load_state(self.env.state_dir).generated[self.target]
        self.assertIsNotNone(record.previous_hash)
        self.assertEqual(self.kinds(), [KEEP])
        self.run_cli("install")
        self.assertIsNone(load_state(self.env.state_dir).generated[self.target].previous_hash)

    def test_failed_publish_after_the_write_ahead_save_is_retried_as_regenerate(self):
        self.run_cli("install")
        old_output = self.target.read_text()
        self.write(self.repo / "codex/instructions.md", "Changed.\n")
        original = installer.write_text_file

        def fail(*args, **kwargs):
            raise OSError("disk full")

        installer.write_text_file = fail
        with self.assertRaises(OSError):
            self.run_cli("install")
        installer.write_text_file = original
        self.assertEqual(self.target.read_text(), old_output)
        self.assertEqual(self.kinds(), [REGENERATE])
        self.assertEqual(self.run_cli("install")[0], 0)
        self.assertEqual(self.target.read_text(), self.output())


class ComposeLifecycleTest(ComposeCycleTestCase):
    def test_prune_restore_and_uninstall(self):
        original = "Hand-written, equal to the body.\n"
        self.write(self.repo / "shared/instructions.md", "")
        self.write(self.repo / "codex/instructions.md", original)
        self.write(self.target, original)
        code, lines = self.run_cli("install")
        (backup_id,) = [line.rsplit(": ", 1)[1] for line in lines if line.startswith("backup ")]

        self.write_manifest()
        self.assertEqual(self.kinds(), ["orphan"])
        self.assertEqual(self.run_cli("install", "--prune")[0], 0)
        self.assertFalse(self.target.exists())
        self.assertEqual(load_state(self.env.state_dir).generated, {})

        self.assertEqual(self.run_cli("restore", backup_id), (0, ["restored: ~/.codex/AGENTS.md"]))
        self.assertEqual(self.target.read_text(), original)

    def test_edited_generated_file_without_entry_is_kept_and_reported(self):
        self.run_cli("install")
        self.write(self.target, self.output() + "Edit.\n")
        self.write_manifest()
        self.assertEqual(self.kinds("--prune"), [])
        self.assertTrue(any("generated file was edited or removed" in line for line in self.run_cli("doctor")[1]))
        code, lines = self.run_cli("uninstall")
        self.assertEqual(code, 1)
        self.assertIn("kept           ~/.codex/AGENTS.md: the generated file was edited after install", lines)
        self.assertTrue(self.target.exists())

    def test_uninstall_removes_unedited_generated_file(self):
        self.run_cli("install")
        self.assertEqual(self.run_cli("uninstall")[0], 0)
        self.assertFalse(self.target.exists())
        self.assertEqual(load_state(self.env.state_dir).generated, {})

    def test_restore_replaces_an_unedited_generated_file(self):
        self.write(self.target, "Shared rule.\n\nCodex rule.\n")
        code, lines = self.run_cli("install")
        (backup_id,) = [line.rsplit(": ", 1)[1] for line in lines if line.startswith("backup ")]
        self.assertEqual(self.run_cli("restore", backup_id)[0], 0)
        self.assertEqual(self.target.read_text(), "Shared rule.\n\nCodex rule.\n")
        self.assertEqual(load_state(self.env.state_dir).generated, {})

    def test_moved_checkout_keeps_ownership(self):
        self.run_cli("install")
        moved = self.repo.parent / "moved-repo"
        self.repo.rename(moved)
        self.repo = moved
        self.assertEqual(self.kinds(), [KEEP])
        self.run_cli("install")
        self.assertEqual(load_state(self.env.state_dir).generated[self.target].repo_root, moved)

    def test_method_changes_between_link_and_generated_file(self):
        claude_md = self.env.claude_home / "CLAUDE.md"
        source = self.write(self.repo / "claude/CLAUDE.md", "Claude rule.\n")
        link_entry = {"id": "instructions/claude", "method": "symlink", "source": "claude/CLAUDE.md", "targets": ["~/.claude/CLAUDE.md"]}
        compose_entry = {"id": "instructions/claude", "method": "compose", "sources": ["claude/CLAUDE.md"], "targets": ["~/.claude/CLAUDE.md"]}

        self.write_manifest([link_entry])
        self.run_cli("install")
        self.write_manifest([compose_entry])
        self.assertEqual(self.kinds(), [REPLACE])
        self.assertEqual(self.run_cli("install")[0], 0)
        self.assertFalse(claude_md.is_symlink())
        state = load_state(self.env.state_dir)
        self.assertIn(claude_md, state.generated)
        self.assertNotIn(claude_md, state.links)

        self.write_manifest([link_entry])
        self.assertEqual(self.kinds(), [REPLACE])
        self.assertEqual(self.run_cli("install")[0], 0)
        self.assertEqual(os.readlink(claude_md), str(source))
        state = load_state(self.env.state_dir)
        self.assertIn(claude_md, state.links)
        self.assertNotIn(claude_md, state.generated)

    def test_diff_shows_current_against_generated(self):
        self.assertEqual(self.run_cli("diff", "instructions/codex"), (0, ["~/.codex/AGENTS.md: missing"]))
        self.run_cli("install")
        self.assertEqual(
            self.run_cli("diff", "instructions/codex"), (0, ["~/.codex/AGENTS.md: identical to the generated output"])
        )
        self.write(self.target, self.output() + "Edit.\n")
        code, lines = self.run_cli("diff", "instructions/codex")
        self.assertEqual(lines[0], "~/.codex/AGENTS.md: differs from the generated output")
        self.assertIn("-Edit.", lines)


class ComposeConcurrencyTest(ComposeCycleTestCase):
    def swap_after_read(self, module, name, replacement_text):
        original = getattr(module, name)

        def read_then_swap(*args):
            result = original(*args)
            self.target.write_text(replacement_text)
            return result

        setattr(module, name, read_then_swap)
        self.addCleanup(setattr, module, name, original)

    def test_foreign_edit_after_the_ownership_read_is_not_regenerated(self):
        self.run_cli("install")
        self.write(self.repo / "codex/instructions.md", "Changed.\n")
        self.swap_after_read(planner_module, "snapshot", "Concurrent foreign edit\n")
        code, lines = self.run_cli("install")
        self.assertEqual(code, 1)
        self.assertEqual(self.target.read_text(), "Concurrent foreign edit\n")

    def test_foreign_edit_after_the_ownership_read_is_not_pruned(self):
        self.run_cli("install")
        self.write_manifest()
        self.swap_after_read(planner_module, "read_regular_file", "Concurrent foreign edit\n")
        self.assertEqual(self.run_cli("install", "--prune")[0], 1)
        self.assertEqual(self.target.read_text(), "Concurrent foreign edit\n")

    def test_foreign_edit_after_the_ownership_read_is_not_uninstalled(self):
        self.run_cli("install")
        self.swap_after_read(uninstall_module, "owned_generated_snapshot", "Concurrent foreign edit\n")
        self.assertEqual(self.run_cli("uninstall")[0], 1)
        self.assertEqual(self.target.read_text(), "Concurrent foreign edit\n")

    def test_crlf_sources_stay_unchanged_on_the_next_run(self):
        (self.repo / "codex/instructions.md").write_bytes(b"Codex rule.\r\nSecond line.\r\n")
        self.assertEqual(self.run_cli("install")[0], 0)
        self.assertEqual(self.kinds(), [KEEP])
        self.assertEqual(
            self.run_cli("diff", "instructions/codex"), (0, ["~/.codex/AGENTS.md: identical to the generated output"])
        )

    def test_diff_does_not_open_a_fifo_target(self):
        self.target.parent.mkdir(parents=True)
        os.mkfifo(self.target)
        self.assertEqual(self.run_cli("diff", "instructions/codex"), (0, [f"~/.codex/AGENTS.md: not a regular file: {self.target}"]))


class ComposePlanningRaceTest(ComposeCycleTestCase):
    def after_capturing(self, path, change):
        original = planner_module.snapshot

        def capture_then_change(target):
            result = original(target)
            if target == path:
                change()
            return result

        planner_module.snapshot = capture_then_change
        self.addCleanup(setattr, planner_module, "snapshot", original)

    def test_parent_redirected_into_the_repository_after_the_read_is_a_conflict(self):
        self.run_cli("install")
        protected = self.write(self.repo / "protected/AGENTS.md", self.target.read_text())
        self.write(self.repo / "codex/instructions.md", "Changed.\n")

        def redirect():
            os.rename(self.env.codex_home, self.home / "real-codex")
            os.symlink(self.repo / "protected", self.env.codex_home)

        self.after_capturing(self.target, redirect)
        code, lines = self.run_cli("install")
        self.assertEqual(code, 1)
        self.assertIn("its location changed while planning", lines[0])
        self.assertEqual(protected.read_text(), (self.home / "real-codex/AGENTS.md").read_text())

    def test_link_swapped_after_the_capture_is_not_relinked(self):
        claude_md = self.env.claude_home / "CLAUDE.md"
        self.write(self.repo / "claude/CLAUDE.md", "Claude rule.\n")
        self.link(claude_md, self.write(self.repo / "old/CLAUDE.md", "Old.\n"))
        self.write_manifest([{"id": "c", "method": "symlink", "source": "claude/CLAUDE.md", "targets": ["~/.claude/CLAUDE.md"]}])

        def swap():
            claude_md.unlink()
            os.symlink(self.home / "foreign.md", claude_md)

        self.after_capturing(claude_md, swap)
        self.assertEqual(self.run_cli("install")[0], 1)
        self.assertEqual(os.readlink(claude_md), str(self.home / "foreign.md"))

    def test_replace_local_overrides_an_edited_generated_file(self):
        self.run_cli("install")
        self.write(self.target, self.output() + "Local edit.\n")
        self.assertEqual(self.kinds("--replace-local", "instructions/codex"), [REPLACE])
        code, lines = self.run_cli("install", "--replace-local", "instructions/codex")
        self.assertEqual(code, 0)
        self.assertEqual(self.target.read_text(), self.output())
        self.assertTrue(any(line.startswith("backup ") for line in lines))

    def test_binary_local_file_is_never_taken_for_an_empty_body(self):
        self.write(self.repo / "shared/instructions.md", "")
        self.write(self.repo / "codex/instructions.md", "")
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"\xff")
        code, lines = self.run_cli("install", "--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("not UTF-8 text", lines[0])
        self.assertEqual(self.target.read_bytes(), b"\xff")


class ComposeInterruptedPublishTest(ComposeCycleTestCase):
    def install_with_failing_publish(self, *argv):
        original = installer.write_text_file

        def fail(*args, **kwargs):
            raise OSError("disk full")

        installer.write_text_file = fail
        try:
            with self.assertRaises(OSError):
                self.run_cli("install", *argv)
        finally:
            installer.write_text_file = original

    def test_failed_first_install_is_retried_as_a_first_install(self):
        self.write(self.target, "Shared rule.\n\nCodex rule.\n")
        self.install_with_failing_publish()
        self.assertEqual(self.target.read_text(), "Shared rule.\n\nCodex rule.\n")
        self.assertTrue(load_state(self.env.state_dir).generated[self.target].pending)
        self.assertTrue(any("install was interrupted" in line for line in self.run_cli("doctor")[1]))
        self.assertEqual(self.kinds(), [REPLACE])
        self.assertEqual(self.run_cli("install")[0], 0)
        self.assertFalse(load_state(self.env.state_dir).generated[self.target].pending)

    def test_failed_conversion_of_a_link_from_a_moved_checkout_is_retried(self):
        claude_md = self.env.claude_home / "CLAUDE.md"
        self.write(self.repo / "claude/CLAUDE.md", "Claude rule.\n")
        self.write_manifest([{"id": "c", "method": "symlink", "source": "claude/CLAUDE.md", "targets": ["~/.claude/CLAUDE.md"]}])
        self.run_cli("install")
        moved = self.repo.parent / "moved-repo"
        self.repo.rename(moved)
        self.repo = moved
        self.write_manifest([{"id": "c", "method": "compose", "sources": ["claude/CLAUDE.md"], "targets": ["~/.claude/CLAUDE.md"]}])

        self.install_with_failing_publish()

        self.assertTrue(claude_md.is_symlink())
        self.assertIn(claude_md, load_state(self.env.state_dir).links)
        self.assertEqual(self.kinds(), [REPLACE])
        self.assertEqual(self.run_cli("install")[0], 0)
        state = load_state(self.env.state_dir)
        self.assertNotIn(claude_md, state.links)
        self.assertFalse(state.generated[claude_md].pending)


class ComposeInterruptedUninstallTest(ComposeCycleTestCase):
    def test_uninstall_right_after_an_interrupted_link_to_compose_change(self):
        claude_md = self.env.claude_home / "CLAUDE.md"
        self.write(self.repo / "claude/CLAUDE.md", "Claude rule.\n")
        self.write_manifest([{"id": "c", "method": "symlink", "source": "claude/CLAUDE.md", "targets": ["~/.claude/CLAUDE.md"]}])
        self.run_cli("install")
        self.write_manifest([{"id": "c", "method": "compose", "sources": ["claude/CLAUDE.md"], "targets": ["~/.claude/CLAUDE.md"]}])
        original = installer.save_state
        calls = []

        def save(*args):
            calls.append(1)
            if len(calls) == 2:
                raise OSError("disk full")
            return original(*args)

        installer.save_state = save
        try:
            with self.assertRaises(OSError):
                self.run_cli("install")
        finally:
            installer.save_state = original
        state = load_state(self.env.state_dir)
        self.assertIn(claude_md, state.links)
        self.assertTrue(state.generated[claude_md].pending)
        self.assertFalse(claude_md.is_symlink())

        code, lines = self.run_cli("uninstall")

        self.assertEqual(code, 0, lines)
        self.assertEqual(lines.count("removed        ~/.claude/CLAUDE.md"), 1)
        self.assertFalse(any(line.startswith("kept") for line in lines))
        self.assertFalse(os.path.lexists(claude_md))
        state = load_state(self.env.state_dir)
        self.assertEqual((state.links, state.generated), ({}, {}))


class GeneratedStateValidationTest(FakeWorldTestCase):
    def test_malformed_generated_records_are_rejected(self):
        good = {"entry": "e", "output": "a" * 64, "previous": None, "sources": {"codex/x.md": "b" * 64}, "repo_root": "/r"}
        cases = [
            {"generated": []},
            {"generated": {"/t": None}},
            {"generated": {"/t": []}},
            {"generated": {"/t": 42}},
            {"generated": {"/t": dict(good, pending="yes")}},
            {"generated": {"relative": good}},
            {"generated": {"/t": dict(good, output="short")}},
            {"generated": {"/t": dict(good, previous="nothex")}},
            {"generated": {"/t": dict(good, sources={})}},
            {"generated": {"/t": dict(good, sources={"../x": "b" * 64})}},
            {"generated": {"/t": dict(good, sources={"/abs": "b" * 64})}},
            {"generated": {"/t": dict(good, repo_root="relative")}},
            {"links": {"/t": {"entry": "e", "link": "/r/x", "repo_root": "/r"}}, "generated": {"/t": good}},
        ]
        for case in cases:
            with self.subTest(case=case):
                self.write(self.env.state_dir / "state.json", json.dumps(dict({"version": 1}, **case)))
                with self.assertRaises(StateError):
                    load_state(self.env.state_dir)
        self.write(self.env.state_dir / "state.json", json.dumps({"version": 1, "links": {}}))
        self.assertEqual(load_state(self.env.state_dir).generated, {})
