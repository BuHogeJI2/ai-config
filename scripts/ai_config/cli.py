from __future__ import annotations

import argparse
import difflib
import os
import sys
from pathlib import Path
from typing import Mapping, Sequence, TextIO

from .doctor import ERROR, LEVELS, WARNING, run_doctor
from .fileops import TargetChangedError
from .adopt import AdoptError, adopt
from .agents import AGENTS
from .backups import list_backups
from .compose import ComposeError, compose
from .installer import apply_plan
from .manifest import OWNERS, Entry, Manifest, ManifestError, load_manifest
from .paths import REPO_ROOT, Environment
from .planner import CONFLICT, CREATE, RELINK, Plan, build_plan, link_destination
from .restore import RestoreError, restore_backup
from .state import StateError, exclusive_lock, load_state
from .trees import TreeError, describe_differences, read_regular_file
from .uninstall import uninstall


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
    out: TextIO | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="ai-config")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="report problems without changing anything")
    install = commands.add_parser("install", help="link and generate managed files")
    install.add_argument("--dry-run", action="store_true", help="print the plan without changing anything")
    install.add_argument("--prune", action="store_true", help="remove links into this repository that have no manifest entry")
    install.add_argument(
        "--replace-local",
        action="append",
        default=[],
        metavar="ID",
        help="replace local content of this entry that differs from the repository (backed up first)",
    )
    diff = commands.add_parser("diff", help="show how a local target differs from the repository")
    diff.add_argument("id", help="manifest entry id")
    adopt_command = commands.add_parser("adopt", help="copy a local skill into the repository and add its manifest entry")
    adopt_command.add_argument("--agent", required=True, choices=AGENTS, help="the agent whose local skill is copied")
    adopt_command.add_argument("--skill", required=True, help="skill folder name")
    adopt_command.add_argument("--to", required=True, choices=OWNERS, dest="owner", help="repository owner folder")
    adopt_command.add_argument(
        "--replace-repo", action="store_true", help="overwrite an existing repository copy with the local one"
    )
    restore = commands.add_parser("restore", help="put a backup back; without an id, list the backups")
    restore.add_argument("backup_id", nargs="?")
    commands.add_parser("uninstall", help="remove the links this tool created; backups are not restored")
    args = parser.parse_args(argv)

    env = Environment.from_env(os.environ if environ is None else environ)
    repo_root = (repo_root or REPO_ROOT).resolve()
    out = out or sys.stdout
    if args.command == "doctor":
        return _doctor(repo_root, env, out)
    if args.command == "restore":
        return _restore(args.backup_id, repo_root, env, out)
    if args.command == "uninstall":
        return _uninstall(repo_root, env, out)
    if args.command == "adopt":
        return _adopt(args, repo_root, env, out)

    try:
        manifest = load_manifest(repo_root / "manifest.json")
    except ManifestError as error:
        for problem in error.problems:
            print(f"error    manifest: {problem}", file=out)
        return 1
    if args.command == "install":
        unknown = sorted(set(args.replace_local) - {entry.id for entry in manifest.entries})
        if unknown:
            print(f"error    --replace-local: no manifest entry {', '.join(unknown)}", file=out)
            return 1
        options = {"prune": args.prune, "replace_local": frozenset(args.replace_local)}
        return _install(manifest, repo_root, env, out, args.dry_run, options)
    return _diff(args.id, manifest, repo_root, env, out)


def _install(manifest: Manifest, repo_root: Path, env: Environment, out: TextIO, dry_run: bool, options: dict) -> int:
    try:
        if dry_run:
            plan = build_plan(repo_root, env, manifest, load_state(env.state_dir), **options)
            return _print_plan(plan, repo_root, env, out)
        with exclusive_lock(env.state_dir):
            state = load_state(env.state_dir)
            plan = build_plan(repo_root, env, manifest, state, **options)
            if _print_plan(plan, repo_root, env, out):
                return 1
            backups = apply_plan(plan, repo_root, state, env.state_dir)
    except (StateError, TargetChangedError, TreeError) as error:
        print(f"error    {error}", file=out)
        return 1
    for backup in backups:
        print(f"backup         {env.shorten(backup.target)}: {backup.id}", file=out)
    print(f"Applied {len(plan.changes)} change(s).", file=out)
    return 0


def _adopt(args: argparse.Namespace, repo_root: Path, env: Environment, out: TextIO) -> int:
    try:
        result = adopt(repo_root, env, args.agent, args.skill, args.owner, args.replace_repo)
    except (AdoptError, TargetChangedError, OSError) as error:
        print(f"error    {error}", file=out)
        return 1
    action = "replaced" if result.replaced_repo_copy else "copied"
    print(f"{action:<14} {env.shorten(result.local)} -> {result.source}", file=out)
    if result.entry_added:
        print(f"manifest       added entry {result.entry_id}", file=out)
    print("Nothing was installed or committed. Next: review with git diff, then ai-config install --dry-run.", file=out)
    return 0


def _restore(backup_id: str | None, repo_root: Path, env: Environment, out: TextIO) -> int:
    if backup_id is None:
        backups = list_backups(env.state_dir)
        for backup in backups:
            print(f"{backup.id}  {backup.kind:<4}  {env.shorten(backup.target)}", file=out)
        if not backups:
            print("No backups.", file=out)
        return 0
    try:
        with exclusive_lock(env.state_dir):
            result = restore_backup(backup_id, load_state(env.state_dir), env.state_dir, repo_root)
    except (StateError, RestoreError, TargetChangedError, TreeError, OSError) as error:
        print(f"error    {error}", file=out)
        return 1
    print(f"{result.outcome}: {env.shorten(result.target)}", file=out)
    return 0


def _uninstall(repo_root: Path, env: Environment, out: TextIO) -> int:
    try:
        with exclusive_lock(env.state_dir):
            result = uninstall(load_state(env.state_dir), env.state_dir, repo_root)
    except (StateError, TargetChangedError) as error:
        print(f"error    {error}", file=out)
        return 1
    for target in result.removed:
        print(f"removed        {env.shorten(target)}", file=out)
    for target, reason in result.kept:
        print(f"kept           {env.shorten(target)}: {reason}", file=out)
    print(f"Removed {len(result.removed)} link(s). Backups stay available: ai-config restore", file=out)
    return 1 if result.kept else 0


def _doctor(repo_root: Path, env: Environment, out: TextIO) -> int:
    findings = sorted(run_doctor(repo_root, env), key=lambda finding: LEVELS.index(finding.level))
    for finding in findings:
        print(f"{finding.level:<8} {finding.message}", file=out)
    errors = sum(finding.level == ERROR for finding in findings)
    warnings = sum(finding.level == WARNING for finding in findings)
    print(f"{errors} error(s), {warnings} warning(s)", file=out)
    return 1 if errors else 0


def _print_plan(plan: Plan, repo_root: Path, env: Environment, out: TextIO) -> int:
    for action in plan.actions:
        line = f"{action.kind:<14} {env.shorten(action.target)}"
        if action.kind in (CREATE, RELINK) and action.source:
            line += f" -> {action.source.relative_to(repo_root)}"
        if action.detail:
            line += f": {action.detail}"
        if action.kind == CONFLICT and action.entry_id:
            line += f" (see: ai-config diff {action.entry_id})"
        print(line, file=out)

    if plan.conflicts:
        print(f"{len(plan.conflicts)} conflict(s): install changes nothing until they are resolved.", file=out)
        return 1
    if plan.orphans:
        print(f"{len(plan.orphans)} orphan link(s): removed only with --prune.", file=out)
    print(f"{len(plan.changes)} change(s) planned." if plan.changes else "Nothing to change.", file=out)
    return 0


def _diff(entry_id: str, manifest: Manifest, repo_root: Path, env: Environment, out: TextIO) -> int:
    entry = next((entry for entry in manifest.entries if entry.id == entry_id), None)
    if entry is None:
        print(f"error    no manifest entry '{entry_id}'", file=out)
        return 1
    if entry.method == "compose":
        return _diff_generated(entry, repo_root, env, out)

    source = repo_root / entry.sources[0]
    source_label = entry.sources[0]
    for target in _diff_targets(entry, env):
        shown = env.shorten(target)
        if target.is_symlink() and link_destination(target) == source:
            print(f"{shown}: linked to {source_label}", file=out)
        elif target.is_symlink():
            print(f"{shown}: link to {link_destination(target)}", file=out)
        elif not target.exists():
            print(f"{shown}: missing", file=out)
        else:
            try:
                lines = describe_differences(target, source, shown, source_label)
            except TreeError as error:
                print(f"{shown}: cannot compare: {error}", file=out)
                continue
            print(f"{shown}: identical to {source_label}" if not lines else f"{shown}: differs from {source_label}", file=out)
            for line in lines:
                print(line, file=out)
    return 0


def _diff_generated(entry: Entry, repo_root: Path, env: Environment, out: TextIO) -> int:
    try:
        output = compose(repo_root, entry.sources).output
    except ComposeError as error:
        print(f"error    {error}", file=out)
        return 1
    for target in (env.expand(target) for target in entry.targets):
        shown = env.shorten(target)
        if target.is_symlink():
            print(f"{shown}: link to {link_destination(target)}", file=out)
            continue
        if not os.path.lexists(target):
            print(f"{shown}: missing", file=out)
            continue
        try:
            data, _ = read_regular_file(target)
        except TreeError as error:
            print(f"{shown}: {error}", file=out)
            continue
        if data == output.encode("utf-8"):
            print(f"{shown}: identical to the generated output", file=out)
            continue
        current = data.decode("utf-8", errors="replace")
        print(f"{shown}: differs from the generated output", file=out)
        for line in difflib.unified_diff(
            current.splitlines(keepends=True), output.splitlines(keepends=True), fromfile=shown, tofile="generated"
        ):
            print(line.rstrip("\n"), file=out)
    return 0


def _diff_targets(entry: Entry, env: Environment) -> list[Path]:
    targets = [env.expand(target) for target in entry.targets]
    if not env.codex_legacy_skills_are_separate:
        return targets
    legacy = [env.codex_legacy_skills / target.name for target in targets if target.parent == env.codex_skills]
    return targets + [path for path in legacy if path.exists() or path.is_symlink()]
