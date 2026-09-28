from __future__ import annotations

import os
import secrets
import shutil
from pathlib import Path
from typing import Callable


class TargetChangedError(Exception):
    pass


def temporary_sibling(path: Path) -> Path:
    return path.with_name(f".{path.name}.ai-config-{secrets.token_hex(4)}")


def write_private_file(path: Path, text: str) -> None:
    temporary = temporary_sibling(path)
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temporary, path)


def write_text_file(path: Path, text: str, unchanged: Callable[[], bool] = lambda: True) -> None:
    """Replace a repository file atomically, keeping its current mode (0644 for a new file).

    `unchanged` runs right before the replacement; if it returns False, TargetChangedError is raised
    and the file is left as it is. The temporary file never outlives a failure.
    """
    mode = path.stat().st_mode & 0o777 if path.exists() and not path.is_symlink() else 0o644
    temporary = temporary_sibling(path)
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(temporary, mode)
        if not unchanged():
            raise TargetChangedError(f"{path} changed while it was being written")
        os.replace(temporary, path)
    except BaseException:
        if os.path.lexists(temporary):
            os.unlink(temporary)
        raise


def create_file(path: Path, text: str, unchanged: Callable[[], bool]) -> None:
    """Create a new 0644 file without ever overwriting one that appears meanwhile."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = temporary_sibling(path)
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(temporary, 0o644)
        if not unchanged():
            raise TargetChangedError(f"{path} changed after the plan was made")
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise TargetChangedError(f"{path} was created by someone else during install")
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def place_symlink(target: Path, link_text: str, unchanged: Callable[[], bool]) -> None:
    """Point `target` at `link_text` by renaming a temporary link into place.

    `unchanged` runs right before the rename; if it returns False, nothing is changed and
    TargetChangedError is raised. A real folder at `target` must be moved aside first,
    because a link cannot be renamed over a non-empty folder.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = temporary_sibling(target)
    os.symlink(link_text, temporary)
    try:
        if not unchanged():
            raise TargetChangedError(f"{target} changed after the plan was made")
        os.replace(temporary, target)
    except BaseException:
        os.unlink(temporary)
        raise


def move_aside(path: Path, unchanged: Callable[[], bool]) -> Path:
    if not unchanged():
        raise TargetChangedError(f"{path} changed after the plan was made")
    aside = temporary_sibling(path)
    os.rename(path, aside)
    return aside


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)
