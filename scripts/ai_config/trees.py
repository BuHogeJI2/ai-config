from __future__ import annotations

import difflib
import hashlib
import os
import stat
from pathlib import Path

IGNORED_NAMES = {".DS_Store"}

Signature = dict[str, tuple]


class TreeError(Exception):
    """A tree could not be read completely or contains something other than files, folders, and links."""


def signature(path: Path) -> Signature:
    """Describe a file or folder tree by relative path, content hash, and executable bit.

    Nested symlinks are described by their link text and never followed. `.DS_Store` files are ignored.
    Raises TreeError for unreadable entries and special files, so they are never reported as identical.
    """
    tree: Signature = {}
    _add(path, ".", tree)
    return tree


def identical(first: Path, second: Path) -> bool:
    return signature(first) == signature(second)


def describe_differences(old: Path, new: Path, old_label: str, new_label: str) -> list[str]:
    """Return unified-diff style lines that turn `old` into `new`; empty only when the trees are identical."""
    old_tree, new_tree = signature(old), signature(new)
    lines: list[str] = []
    for relative in sorted(old_tree.keys() | new_tree.keys()):
        before, after = old_tree.get(relative), new_tree.get(relative)
        if before == after:
            continue
        if before is None:
            lines.append(f"only in {new_label}: {relative}")
        elif after is None:
            lines.append(f"only in {old_label}: {relative}")
        elif before[0] == after[0] == "file" and before[1] == after[1]:
            lines.append(f"executable bit differs: {relative}")
        elif before[0] == after[0] == "file":
            lines += _text_diff(_child(old, relative), _child(new, relative), old_label, new_label, relative)
        elif before[0] == after[0] == "link":
            lines.append(f"link differs: {relative} (-> {before[1]} in {old_label}, -> {after[1]} in {new_label})")
        else:
            lines.append(f"type differs: {relative} ({before[0]} in {old_label}, {after[0]} in {new_label})")
    return lines


def _add(path: Path, relative: str, tree: Signature) -> None:
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            tree[relative] = ("link", os.readlink(path))
        elif stat.S_ISREG(info.st_mode):
            tree[relative] = ("file", hashlib.sha256(path.read_bytes()).hexdigest(), _executable(info))
        elif stat.S_ISDIR(info.st_mode):
            tree[relative] = ("dir",)
            for child in sorted(os.listdir(path)):
                if child not in IGNORED_NAMES:
                    _add(path / child, child if relative == "." else f"{relative}/{child}", tree)
        else:
            raise TreeError(f"unsupported file type: {path}")
    except OSError as error:
        raise TreeError(f"cannot read {path}: {error.strerror or error}")


def _executable(info: os.stat_result) -> bool:
    return bool(info.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


def _child(root: Path, relative: str) -> Path:
    return root if relative == "." else root / relative


def _text_diff(old: Path, new: Path, old_label: str, new_label: str, relative: str) -> list[str]:
    old_name = old_label if relative == "." else f"{old_label}/{relative}"
    new_name = new_label if relative == "." else f"{new_label}/{relative}"
    try:
        old_text = old.read_bytes().decode("utf-8")
        new_text = new.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return [f"binary files differ: {old_name} and {new_name}"]
    if "\0" in old_text or "\0" in new_text:
        return [f"binary files differ: {old_name} and {new_name}"]
    lines = [
        line.rstrip("\n")
        for line in difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=old_name,
            tofile=new_name,
        )
    ]
    return lines or [f"files differ: {old_name} and {new_name}"]
