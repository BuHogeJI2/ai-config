from __future__ import annotations

import os
from pathlib import Path

from .backups import Backup, create_backup, prune_backups
from .compose import ComposeError, current_source_hashes, text_hash
from .fileops import TargetChangedError, create_file, move_aside, place_symlink, remove_path, write_text_file
from .paths import is_below
from .planner import (
    CHANGES,
    CREATE,
    KEEP,
    PRUNE,
    REGENERATE,
    RELINK,
    REMOVE_LEGACY,
    REPLACE,
    Action,
    Plan,
    effective_location,
)
from .state import GeneratedRecord, LinkRecord, State, save_state
from .trees import TreeError, snapshot


def apply_plan(plan: Plan, repo_root: Path, state: State, state_dir: Path) -> list[Backup]:
    """Apply a conflict-free plan, saving the state after every change.

    Each target is checked against its planning-time location and snapshot before its backup and
    again right before the rename. A mismatch raises TargetChangedError; changes made so far stay recorded.
    """
    if plan.conflicts:
        raise ValueError("a plan with conflicts must not be applied")
    state.repo_root = repo_root
    backups: list[Backup] = []
    for action in plan.actions:
        if action.kind == KEEP:
            _require_unchanged(action, repo_root)
            if action.output is not None:
                _record_generated(action, state, repo_root)
            else:
                state.links[action.target] = LinkRecord(action.entry_id, os.readlink(action.target), repo_root)
                state.generated.pop(action.target, None)
            continue
        if action.kind not in CHANGES:
            continue
        _require_unchanged(action, repo_root)
        if action.output is not None:
            _record_generated(action, state, repo_root, write_ahead=True)
            save_state(state_dir, state)
            backups += _write_generated(action, repo_root, state_dir)
            _record_generated(action, state, repo_root)
            save_state(state_dir, state)
            continue
        if action.kind == CREATE:
            place_symlink(action.target, str(action.source), lambda: _unchanged(action, repo_root))
        elif action.kind == RELINK:
            backups.append(create_backup(state_dir, action.target))
            place_symlink(action.target, str(action.source), lambda: _unchanged(action, repo_root))
        elif action.kind == REPLACE:
            backups.append(_replace_with_link(action, repo_root, state_dir))
        elif action.kind in (REMOVE_LEGACY, PRUNE):
            backups.append(create_backup(state_dir, action.target))
            remove_path(move_aside(action.target, lambda: _unchanged(action, repo_root)))
            state.links.pop(action.target, None)
            state.generated.pop(action.target, None)
        if action.kind in (CREATE, RELINK, REPLACE):
            state.links[action.target] = LinkRecord(action.entry_id, str(action.source), repo_root)
            state.generated.pop(action.target, None)
        save_state(state_dir, state)
    save_state(state_dir, state)
    for target in sorted({backup.target for backup in backups}):
        prune_backups(state_dir, target)
    return backups


def _write_generated(action: Action, repo_root: Path, state_dir: Path) -> list[Backup]:
    if action.kind == CREATE:
        create_file(action.target, action.output, lambda: _unchanged(action, repo_root))
        return []
    backup = create_backup(state_dir, action.target)
    write_text_file(action.target, action.output, unchanged=lambda: _unchanged(action, repo_root))
    return [backup]


def _record_generated(action: Action, state: State, repo_root: Path, write_ahead: bool = False) -> None:
    """Record a generated file.

    The write-ahead record, saved before publishing, is pending: it keeps the previous output hash only
    when the current bytes were ours, and it leaves any link record in place, so an interrupted run is
    retried from what was really there before. The final record clears both.
    """
    hashes = dict(action.source_hashes)
    if not write_ahead:
        state.links.pop(action.target, None)
        state.generated[action.target] = GeneratedRecord(action.entry_id, text_hash(action.output), hashes, repo_root)
        return
    previous = None
    old = state.generated.get(action.target)
    if old is not None and action.expected[0] == "tree":
        current = dict(action.expected[1]).get(".")
        if current and current[0] == "file" and current[1] in old.owned_hashes:
            previous = current[1]
    state.generated[action.target] = GeneratedRecord(
        action.entry_id, text_hash(action.output), hashes, repo_root, previous, pending=True
    )


def _replace_with_link(action: Action, repo_root: Path, state_dir: Path) -> Backup:
    backup = create_backup(state_dir, action.target)
    aside = move_aside(action.target, lambda: _unchanged(action, repo_root))
    try:
        place_symlink(action.target, str(action.source), lambda: _still_empty(action, repo_root))
    except BaseException as error:
        if os.path.lexists(action.target):
            raise TargetChangedError(
                f"{action.target} was created by someone else during install; "
                f"the original content is kept at {aside} and in backup {backup.id}"
            ) from error
        os.rename(aside, action.target)
        raise
    remove_path(aside)
    return backup


def _require_unchanged(action: Action, repo_root: Path) -> None:
    if not _unchanged(action, repo_root):
        raise TargetChangedError(f"{action.target} changed after the plan was made")


def _unchanged(action: Action, repo_root: Path) -> bool:
    try:
        return (
            effective_location(action.target) == action.location
            and snapshot(action.target) == action.expected
            and _source_is_valid(action, repo_root)
        )
    except TreeError:
        return False


def _still_empty(action: Action, repo_root: Path) -> bool:
    return (
        not os.path.lexists(action.target)
        and effective_location(action.target) == action.location
        and _source_is_valid(action, repo_root)
    )


def _source_is_valid(action: Action, repo_root: Path) -> bool:
    if action.kind == PRUNE:
        return True
    if action.output is not None:
        return _compose_sources_unchanged(action, repo_root)
    return action.source is not None and action.source.exists() and is_below(action.source.resolve(), repo_root)


def _compose_sources_unchanged(action: Action, repo_root: Path) -> bool:
    try:
        return current_source_hashes(repo_root, tuple(action.source_hashes)) == action.source_hashes
    except ComposeError:
        return False
