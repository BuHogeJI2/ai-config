from __future__ import annotations

import errno
import fcntl
import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
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


@dataclass(frozen=True)
class GeneratedRecord:
    """A generated file.

    Between the write-ahead save and the final save the record is `pending`: the new output may not be
    published yet. `previous_hash` then names the previous output only if that output was ours, and a
    link record for the same target is kept until publishing succeeds.
    """

    entry_id: str
    output_hash: str
    source_hashes: dict[str, str]
    repo_root: Path
    previous_hash: str | None = None
    pending: bool = False

    @property
    def owned_hashes(self) -> set[str]:
        return {self.output_hash} | ({self.previous_hash} if self.previous_hash else set())


@dataclass
class State:
    repo_root: Path | None = None
    links: dict[Path, LinkRecord] = field(default_factory=dict)
    generated: dict[Path, GeneratedRecord] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "version": STATE_VERSION,
            "repo_root": str(self.repo_root) if self.repo_root else None,
            "links": {
                str(target): {"entry": record.entry_id, "link": record.link_text, "repo_root": str(record.repo_root)}
                for target, record in sorted(self.links.items())
            },
            "generated": {
                str(target): {
                    "entry": record.entry_id,
                    "output": record.output_hash,
                    "previous": record.previous_hash,
                    "pending": record.pending,
                    "sources": dict(sorted(record.source_hashes.items())),
                    "repo_root": str(record.repo_root),
                }
                for target, record in sorted(self.generated.items())
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
    generated = data.get("generated", {})
    if not isinstance(generated, dict):
        raise StateError(f"{path} has malformed generated records")
    generated_records = {}
    for target, record in generated.items():
        if not isinstance(record, dict):
            raise StateError(f"{path} has a malformed generated record for {target!r}")
        sources = record.get("sources")
        if not (
            _is_absolute_path(target)
            and isinstance(record.get("pending", False), bool)
            and isinstance(record.get("entry"), str)
            and _is_sha256(record.get("output"))
            and (record.get("previous") is None or _is_sha256(record.get("previous")))
            and isinstance(sources, dict)
            and sources
            and all(_is_repo_relative(key) and _is_sha256(value) for key, value in sources.items())
            and _is_absolute_path(record.get("repo_root"))
        ):
            raise StateError(f"{path} has a malformed generated record for {target!r}")
        if Path(target) in records and not record.get("pending", False):
            raise StateError(f"{path} records {target!r} as both a link and a generated file")
        generated_records[Path(target)] = GeneratedRecord(
            record["entry"],
            record["output"],
            dict(sources),
            Path(record["repo_root"]),
            record.get("previous"),
            record.get("pending", False),
        )
    return State(repo_root=Path(repo_root) if repo_root else None, links=records, generated=generated_records)


def _is_absolute_path(value: object) -> bool:
    return isinstance(value, str) and os.path.isabs(value)


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _is_repo_relative(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    pure = PurePosixPath(value)
    return str(pure) == value and value != "." and not pure.is_absolute() and ".." not in pure.parts


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
