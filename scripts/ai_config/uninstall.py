from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .fileops import move_aside, remove_path
from .paths import is_below
from .planner import effective_location
from .restore import is_managed_link, protected_roots
from .state import State, save_state


@dataclass(frozen=True)
class UninstallResult:
    removed: list[Path]
    kept: list[tuple[Path, str]]


def uninstall(state: State, state_dir: Path, repo_root: Path) -> UninstallResult:
    """Remove every link the state file records, but only while it still has the recorded text and origin.

    Changed links, and links whose location resolves into a repository checkout, are kept and reported.
    Ordinary files are never removed, and backups are not restored.
    """
    roots = protected_roots(state, repo_root)
    removed: list[Path] = []
    kept: list[tuple[Path, str]] = []
    for target, record in sorted(state.links.items()):
        location = effective_location(target)
        if any(is_below(location, root) for root in roots):
            kept.append((target, f"its location resolves into a repository checkout: {location}"))
            continue
        if not os.path.lexists(target):
            del state.links[target]
        elif is_managed_link(target, state, repo_root) and os.readlink(target) == record.link_text:
            link_text = record.link_text
            aside = move_aside(
                target,
                lambda: effective_location(target) == location
                and target.is_symlink()
                and os.readlink(target) == link_text,
            )
            remove_path(aside)
            removed.append(target)
            del state.links[target]
        else:
            kept.append((target, "the link was changed after install"))
        save_state(state_dir, state)
    save_state(state_dir, state)
    return UninstallResult(removed, kept)
