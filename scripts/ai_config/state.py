from __future__ import annotations

import errno
import fcntl
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .fileops import write_private_file

STATE_VERSION = 1


class StateError(Exception):
    pass


@dataclass(frozen=True)
class LinkRecord:
    entry_id: str
    link_text: str
    repo_root: Path


@dataclass
class State:
    repo_root: Path | None = None
    links: dict[Path, LinkRecord] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "version": STATE_VERSION,
            "repo_root": str(self.repo_root) if self.repo_root else None,
            "links": {
                str(target): {"entry": record.entry_id, "link": record.link_text, "repo_root": str(record.repo_root)}
                for target, record in sorted(self.links.items())
            },
        }


def state_file(state_dir: Path) -> Path:
    return state_dir / "state.json"


def load_state(state_dir: Path) -> State:
    path = state_file(state_dir)
    if not path.exists():
        return State()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise StateError(f"{path} is not valid JSON: {error}")
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        raise StateError(f"{path} has an unsupported format")
    repo_root = data.get("repo_root")
    links = data.get("links", {})
    if not (repo_root is None or _is_absolute_path(repo_root)) or not isinstance(links, dict):
        raise StateError(f"{path} has a malformed repo_root or links")
    records = {}
    for target, record in links.items():
        if not (
            _is_absolute_path(target)
            and isinstance(record, dict)
            and isinstance(record.get("entry"), str)
            and isinstance(record.get("link"), str)
            and record["link"]
            and _is_absolute_path(record.get("repo_root"))
        ):
            raise StateError(f"{path} has a malformed link record for {target!r}")
        records[Path(target)] = LinkRecord(record["entry"], record["link"], Path(record["repo_root"]))
    return State(repo_root=Path(repo_root) if repo_root else None, links=records)


def _is_absolute_path(value: object) -> bool:
    return isinstance(value, str) and os.path.isabs(value)


def save_state(state_dir: Path, state: State) -> None:
    ensure_private_dir(state_dir)
    write_private_file(state_file(state_dir), json.dumps(state.to_json(), indent=2) + "\n")


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)


@contextmanager
def exclusive_lock(state_dir: Path) -> Iterator[None]:
    ensure_private_dir(state_dir)
    descriptor = os.open(state_dir / "lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in (errno.EAGAIN, errno.EACCES):
                raise StateError("another ai-config run holds the lock")
            raise
        yield
    finally:
        os.close(descriptor)
