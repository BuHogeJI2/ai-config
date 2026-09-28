from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .backups import backups_dir, read_meta
from .fileops import TargetChangedError, move_aside, remove_path, temporary_sibling
from .paths import is_below
from .planner import effective_location, link_destination, points_into
from .state import State, save_state
from .trees import TreeError, signature, snapshot


class RestoreError(Exception):
    pass


@dataclass(frozen=True)
class RestoreResult:
    target: Path
    outcome: str


def protected_roots(state: State, repo_root: Path) -> set[Path]:
    """This repository and every checkout a recorded link came from; nothing inside them is ever changed."""
    return {repo_root.resolve()} | {record.repo_root for record in state.links.values()}


def is_managed_link(target: Path, state: State, repo_root: Path) -> bool:
    """True for a link into this repository, or a link that still has the text and origin the state records."""
    if not target.is_symlink():
        return False
    if points_into(target, repo_root):
        return True
    record = state.links.get(target)
    return (
        record is not None
        and os.readlink(target) == record.link_text
        and is_below(link_destination(target), record.repo_root)
    )


def restore_backup(backup_id: str, state: State, state_dir: Path, repo_root: Path) -> RestoreResult:
    """Put a backup back at its original location with its original modes.

    A managed link at the target is replaced. Ordinary local content is accepted only when it already
    equals the backup, in which case only its modes are restored; anything else raises RestoreError.
    """
    folder = backups_dir(state_dir) / backup_id
    if "/" in backup_id or backup_id in (".", "..") or not folder.is_dir():
        raise RestoreError(f"no backup '{backup_id}'")
    meta = read_meta(folder)
    if not meta:
        raise RestoreError(f"backup '{backup_id}' has no readable metadata")
    target = Path(meta["target"])

    location = effective_location(target)
    if any(is_below(location, root) for root in protected_roots(state, repo_root)):
        raise RestoreError(f"{target} resolves into a repository checkout: {location}")
    try:
        before = snapshot(target)
    except TreeError as error:
        raise RestoreError(str(error))

    def unchanged() -> bool:
        try:
            return effective_location(target) == location and snapshot(target) == before
        except TreeError:
            return False

    if _content_matches(target, folder, meta):
        _restore_modes(target, meta, unchanged)
        _forget(target, state, state_dir)
        return RestoreResult(target, "already restored")
    managed = is_managed_link(target, state, repo_root)
    if before != ("missing",) and not managed:
        raise RestoreError(f"{target} has local content that differs from the backup; move it away first")

    staged = _stage(folder, meta, target)
    aside = None
    try:
        if managed:
            aside = move_aside(target, unchanged)
        if os.path.lexists(target) or effective_location(target) != location:
            raise TargetChangedError(f"{target} changed while restoring")
        _place_without_overwriting(staged, target)
    except BaseException as error:
        if os.path.lexists(staged):
            remove_path(staged)
        if aside is not None:
            if os.path.lexists(target):
                raise TargetChangedError(f"{target} was created by someone else; the previous link is kept at {aside}") from error
            os.rename(aside, target)
        raise
    if aside is not None:
        remove_path(aside)
    _forget(target, state, state_dir)
    return RestoreResult(target, "restored")


def _forget(target: Path, state: State, state_dir: Path) -> None:
    state.links.pop(target, None)
    save_state(state_dir, state)


def _place_without_overwriting(staged: Path, target: Path) -> None:
    if staged.is_dir() and not staged.is_symlink():
        os.rename(staged, target)
        return
    os.link(staged, target, follow_symlinks=False)
    os.unlink(staged)


def _stage(folder: Path, meta: dict, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = temporary_sibling(target)
    if meta["kind"] == "link":
        os.symlink(meta["link"], staged)
        return staged
    _copy_with_modes(folder / "content", staged, ".", meta["modes"])
    return staged


def _copy_with_modes(source: Path, destination: Path, relative: str, modes: dict[str, int]) -> None:
    if source.is_symlink():
        os.symlink(os.readlink(source), destination)
        return
    if source.is_dir():
        destination.mkdir(mode=0o700)
        for child in sorted(source.iterdir()):
            child_relative = child.name if relative == "." else f"{relative}/{child.name}"
            _copy_with_modes(child, destination / child.name, child_relative, modes)
    else:
        destination.write_bytes(source.read_bytes())
    destination.chmod(modes[relative])


def _content_matches(target: Path, folder: Path, meta: dict) -> bool:
    if meta["kind"] == "link":
        return target.is_symlink() and os.readlink(target) == meta["link"]
    if target.is_symlink() or not target.exists():
        return False
    try:
        return signature(target) == _backup_signature(folder, meta)
    except TreeError:
        return False


def _backup_signature(folder: Path, meta: dict) -> dict:
    """Signature of the backed-up content with the original executable bits, since backup files are all 0600."""
    backed_up = signature(folder / "content")
    for relative, entry in backed_up.items():
        if entry[0] == "file":
            backed_up[relative] = (entry[0], entry[1], bool(meta["modes"][relative] & 0o111))
    return backed_up


def _restore_modes(target: Path, meta: dict, unchanged) -> None:
    """Set the recorded modes, checking before every change that the target is still the one compared."""
    if meta["kind"] == "link":
        return
    for relative, mode in sorted(meta["modes"].items(), key=lambda item: item[0].count("/"), reverse=True):
        path = target if relative == "." else target / relative
        if not unchanged():
            raise TargetChangedError(f"{target} changed while restoring its modes")
        if not path.is_symlink() and stat.S_IMODE(path.lstat().st_mode) != mode:
            path.chmod(mode)
