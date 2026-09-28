from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .fileops import move_aside, remove_path
from .paths import is_below
from .planner import effective_location, owned_generated_snapshot
from .restore import is_managed_link, protected_roots
from .state import State, save_state
from .trees import TreeError, snapshot


@dataclass(frozen=True)
class UninstallResult:
    removed: list[Path]
    kept: list[tuple[Path, str]]


def uninstall(state: State, state_dir: Path, repo_root: Path) -> UninstallResult:
    """Remove every link and generated file the state file records, but only while it is unchanged.

    Each target is handled once, even when an interrupted install left both a link record and a pending
    generated record for it. Changed targets, and targets whose location resolves into a repository
    checkout, are kept and reported. Ordinary files are never removed, and backups are not restored.
    """
    roots = protected_roots(state, repo_root)
    removed: list[Path] = []
    kept: list[tuple[Path, str]] = []
    for target in sorted(set(state.links) | set(state.generated)):
        link_record = state.links.get(target)
        generated = state.generated.get(target)
        location = effective_location(target)
        if any(is_below(location, root) for root in roots):
            kept.append((target, f"its location resolves into a repository checkout: {location}"))
            continue
        if not os.path.lexists(target):
            _forget(target, state)
        else:
            owned = owned_generated_snapshot(target, state) if generated else None
            if owned is None and link_record and is_managed_link(target, state, repo_root):
                if os.readlink(target) == link_record.link_text:
                    owned = ("link", link_record.link_text)
            if owned is not None:
                aside = move_aside(
                    target, lambda: effective_location(target) == location and _snapshot_or_none(target) == owned
                )
                remove_path(aside)
                removed.append(target)
                _forget(target, state)
            elif generated is not None and generated.pending and link_record is None:
                _forget(target, state)
            elif generated is not None and not generated.pending:
                kept.append((target, "the generated file was edited after install"))
            else:
                kept.append((target, "the link was changed after install"))
        save_state(state_dir, state)
    save_state(state_dir, state)
    return UninstallResult(removed, kept)


def _forget(target: Path, state: State) -> None:
    state.links.pop(target, None)
    state.generated.pop(target, None)


def _snapshot_or_none(path: Path) -> tuple | None:
    try:
        return snapshot(path)
    except TreeError:
        return None
