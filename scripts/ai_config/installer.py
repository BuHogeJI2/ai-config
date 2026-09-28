from __future__ import annotations

import os
from pathlib import Path

from .backups import Backup, create_backup, prune_backups
from .fileops import TargetChangedError, move_aside, place_symlink, remove_path
from .paths import is_below
from .planner import CHANGES, CREATE, KEEP, RELINK, REMOVE_LEGACY, REPLACE, Action, Plan, effective_location
from .state import LinkRecord, State, save_state
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
            state.links[action.target] = LinkRecord(action.entry_id, os.readlink(action.target), repo_root)
            continue
        if action.kind not in CHANGES:
            continue
        _require_unchanged(action, repo_root)
        if action.kind == CREATE:
            place_symlink(action.target, str(action.source), lambda: _unchanged(action, repo_root))
        elif action.kind == RELINK:
            backups.append(create_backup(state_dir, action.target))
            place_symlink(action.target, str(action.source), lambda: _unchanged(action, repo_root))
        elif action.kind == REPLACE:
            backups.append(_replace_with_link(action, repo_root, state_dir))
        elif action.kind == REMOVE_LEGACY:
            backups.append(create_backup(state_dir, action.target))
            remove_path(move_aside(action.target, lambda: _unchanged(action, repo_root)))
        if action.kind in (CREATE, RELINK, REPLACE):
            state.links[action.target] = LinkRecord(action.entry_id, str(action.source), repo_root)
        save_state(state_dir, state)
    save_state(state_dir, state)
    for target in sorted({backup.target for backup in backups}):
        prune_backups(state_dir, target)
    return backups


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
    return action.source is not None and action.source.exists() and is_below(action.source.resolve(), repo_root)
