from __future__ import annotations

import json
import os
import shutil
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .fileops import write_private_file
from .state import ensure_private_dir

BACKUPS_KEPT_PER_TARGET = 5


class BackupError(Exception):
    pass


@dataclass(frozen=True)
class Backup:
    id: str
    target: Path
    kind: str
    path: Path


def backups_dir(state_dir: Path) -> Path:
    return state_dir / "backups"


def create_backup(state_dir: Path, target: Path) -> Backup:
    """Copy `target` into a new private backup; files get mode 0600 and folders 0700.

    The original modes are kept in the backup metadata so a restore can put them back.
    """
    root = backups_dir(state_dir)
    ensure_private_dir(state_dir)
    ensure_private_dir(root)
    backup_path = _new_backup_folder(root)
    modes: dict[str, int] = {}
    kind = "link" if target.is_symlink() else "dir" if target.is_dir() else "file"
    if kind != "link":
        _copy_private(target, backup_path / "content", ".", modes)
    meta = {
        "target": str(target),
        "kind": kind,
        "created": datetime.now().isoformat(timespec="seconds"),
        "link": os.readlink(target) if kind == "link" else None,
        "modes": modes,
    }
    write_private_file(backup_path / "meta.json", json.dumps(meta, indent=2) + "\n")
    return Backup(id=backup_path.name, target=target, kind=kind, path=backup_path)


def list_backups(state_dir: Path) -> list[Backup]:
    root = backups_dir(state_dir)
    if not root.is_dir():
        return []
    backups = []
    for folder in sorted(root.iterdir()):
        meta = read_meta(folder)
        if meta:
            backups.append(Backup(id=folder.name, target=Path(meta["target"]), kind=meta["kind"], path=folder))
    return backups


def read_meta(folder: Path) -> dict | None:
    try:
        return json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def prune_backups(state_dir: Path, target: Path, keep: int = BACKUPS_KEPT_PER_TARGET) -> list[Backup]:
    for_target = [backup for backup in list_backups(state_dir) if backup.target == target]
    removed = for_target[:-keep] if len(for_target) > keep else []
    for backup in removed:
        shutil.rmtree(backup.path)
    return removed


def _new_backup_folder(root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    for suffix in range(100):
        folder = root / (stamp if suffix == 0 else f"{stamp}-{suffix}")
        try:
            folder.mkdir(mode=0o700)
        except FileExistsError:
            continue
        folder.chmod(0o700)
        return folder
    raise FileExistsError(f"could not create a backup folder in {root}")


def _copy_private(source: Path, destination: Path, relative: str, modes: dict[str, int]) -> None:
    if source.is_symlink():
        os.symlink(os.readlink(source), destination)
        return
    modes[relative] = stat.S_IMODE(source.lstat().st_mode)
    if source.is_dir():
        destination.mkdir(mode=0o700)
        destination.chmod(0o700)
        for child in sorted(source.iterdir()):
            child_relative = child.name if relative == "." else f"{relative}/{child.name}"
            _copy_private(child, destination / child.name, child_relative, modes)
        return
    reader = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(reader, "rb") as original:
        if not stat.S_ISREG(os.fstat(original.fileno()).st_mode):
            raise BackupError(f"cannot back up {source}: not a regular file")
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            shutil.copyfileobj(original, handle)
