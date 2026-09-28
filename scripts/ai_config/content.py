from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

FORBIDDEN_NAMES = {
    ".env",
    ".claude.json",
    ".credentials.json",
    "auth.json",
    "credentials.json",
    "default.rules",
    "history.jsonl",
}
FORBIDDEN_SUFFIXES = (".db", ".log", ".sqlite", ".sqlite3")
SECRET_PATTERNS = (
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("API key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
)
HOME_PATH = re.compile(r"(?<![\w.~-])/(?:Users|home)/[A-Za-z0-9._-]+")
MAX_SCANNED_BYTES = 1_000_000


@dataclass(frozen=True)
class ContentProblem:
    relative: str
    line: int | None
    message: str

    def __str__(self) -> str:
        where = self.relative if self.line is None else f"{self.relative}:{self.line}"
        return f"{where}: {self.message}"


def is_forbidden_file(name: str) -> bool:
    if name.startswith(".env.") and name != ".env.example":
        return True
    return name in FORBIDDEN_NAMES or name.endswith(FORBIDDEN_SUFFIXES)


def scan_tree(
    root: Path, check_home_paths: Callable[[str], bool], skipped_dirs: frozenset[str] = frozenset()
) -> list[ContentProblem]:
    """Report forbidden files, likely secrets, and (where asked) absolute home paths under `root`."""
    problems: list[ContentProblem] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(name for name in dirs if name not in skipped_dirs)
        for name in sorted(files):
            path = Path(current) / name
            relative = path.relative_to(root).as_posix()
            if is_forbidden_file(name):
                problems.append(ContentProblem(relative, None, "forbidden file"))
                continue
            text = _read_text(path)
            if text is not None:
                problems += _scan_text(relative, text, check_home_paths(relative))
    return problems


def _scan_text(relative: str, text: str, check_home_paths: bool) -> list[ContentProblem]:
    problems = []
    for number, line in enumerate(text.splitlines(), start=1):
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                problems.append(ContentProblem(relative, number, f"possible {label}"))
        if check_home_paths:
            match = HOME_PATH.search(line)
            if match:
                problems.append(ContentProblem(relative, number, f"absolute home path {match.group(0)}"))
    return problems


def _read_text(path: Path) -> str | None:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SCANNED_BYTES:
        return None
    data = path.read_bytes()
    if b"\0" in data:
        return None
    return data.decode("utf-8", errors="replace")
