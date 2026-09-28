from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

METHODS = ("symlink", "compose")
OWNERS = ("shared", "codex", "claude")

_ENTRY_KEYS = {"id", "method", "source", "sources", "targets", "requires"}
_REQUIRES_KEYS = {"commands", "mcp"}
_NAME = r"[A-Za-z0-9_][A-Za-z0-9._-]*"
_TARGET = re.compile(
    rf"~/\.agents/skills/{_NAME}"
    rf"|~/\.claude/skills/{_NAME}"
    r"|~/\.claude/CLAUDE\.md"
    rf"|~/\.claude/rules/{_NAME}\.md"
    r"|~/\.codex/AGENTS\.md"
)


class ManifestError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Entry:
    id: str
    method: str
    sources: tuple[str, ...]
    targets: tuple[str, ...]
    requires: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class Manifest:
    external: tuple[str, ...]
    entries: tuple[Entry, ...]

    def entry_for_source(self, source: str) -> Entry | None:
        return next((entry for entry in self.entries if source in entry.sources), None)

    def is_external(self, name: str) -> bool:
        return name.lower() in {external.lower() for external in self.external}


def is_manageable_name(name: str) -> bool:
    return re.fullmatch(_NAME, name) is not None


def skill_targets(owner: str, name: str) -> tuple[str, ...]:
    codex = f"~/.agents/skills/{name}"
    claude = f"~/.claude/skills/{name}"
    return {"shared": (codex, claude), "codex": (codex,), "claude": (claude,)}[owner]


def load_manifest(path: Path) -> Manifest:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ManifestError([f"{path.name} not found"])
    except json.JSONDecodeError as error:
        raise ManifestError([f"{path.name} is not valid JSON: {error}"])
    return parse_manifest(data)


def parse_manifest(data: Any) -> Manifest:
    problems: list[str] = []
    if not isinstance(data, dict):
        raise ManifestError(["manifest must be a JSON object"])

    unknown = set(data) - {"version", "external", "entries"}
    if unknown:
        problems.append(f"unknown manifest keys: {', '.join(sorted(unknown))}")
    if data.get("version") != 1:
        problems.append("manifest version must be 1")

    external = data.get("external", [])
    if not _is_string_list(external):
        problems.append("'external' must be a list of skill names")
        external = []

    raw_entries = data.get("entries", [])
    if not isinstance(raw_entries, list):
        problems.append("'entries' must be a list")
        raw_entries = []

    entries: list[Entry] = []
    for index, raw in enumerate(raw_entries):
        entry = _parse_entry(raw, f"entries[{index}]", problems)
        if entry:
            entries.append(entry)

    _check_protected_targets(entries, external, problems)
    _check_compose_targets(entries, problems)
    _check_unique([entry.id for entry in entries], "entry id", problems)
    _check_unique([target for entry in entries for target in entry.targets], "target", problems)

    if problems:
        raise ManifestError(problems)
    return Manifest(external=tuple(external), entries=tuple(entries))


def _parse_entry(raw: Any, where: str, problems: list[str]) -> Entry | None:
    if not isinstance(raw, dict):
        problems.append(f"{where} must be an object")
        return None
    count_before = len(problems)

    unknown = set(raw) - _ENTRY_KEYS
    if unknown:
        problems.append(f"{where}: unknown keys: {', '.join(sorted(unknown))}")

    entry_id = raw.get("id")
    if not isinstance(entry_id, str) or not entry_id:
        problems.append(f"{where}: 'id' must be a non-empty string")
    else:
        where = f"entry '{entry_id}'"

    method = raw.get("method")
    if method not in METHODS:
        problems.append(f"{where}: 'method' must be one of {', '.join(METHODS)}")

    sources = _parse_sources(raw, method, where, problems)
    targets = _parse_targets(raw, where, problems)
    requires = _parse_requires(raw.get("requires", {}), where, problems)

    if len(problems) > count_before:
        return None
    return Entry(id=entry_id, method=method, sources=sources, targets=targets, requires=requires)


def _parse_sources(raw: dict, method: Any, where: str, problems: list[str]) -> tuple[str, ...]:
    if "source" in raw and "sources" in raw:
        problems.append(f"{where}: use either 'source' or 'sources', not both")
        return ()
    if method == "symlink":
        sources = [raw.get("source")]
        if not isinstance(raw.get("source"), str):
            problems.append(f"{where}: symlink entries need a 'source' string")
            return ()
    elif method == "compose":
        sources = raw.get("sources")
        if not _is_string_list(sources) or not sources:
            problems.append(f"{where}: compose entries need a non-empty 'sources' list")
            return ()
    else:
        return ()

    for source in sources:
        if not _is_repo_relative(source):
            problems.append(f"{where}: source must be a relative path inside the repository: {source}")
    return tuple(sources)


def _parse_targets(raw: dict, where: str, problems: list[str]) -> tuple[str, ...]:
    targets = raw.get("targets")
    if not _is_string_list(targets) or not targets:
        problems.append(f"{where}: 'targets' must be a non-empty list of strings")
        return ()
    for target in targets:
        if not _TARGET.fullmatch(target):
            problems.append(f"{where}: unsupported target {target}; allowed: a skill folder, CLAUDE.md, a Claude rules file, or AGENTS.md")
    return tuple(targets)


def _parse_requires(requires: Any, where: str, problems: list[str]) -> dict[str, tuple[str, ...]]:
    if not isinstance(requires, dict):
        problems.append(f"{where}: 'requires' must be an object")
        return {}
    unknown = set(requires) - _REQUIRES_KEYS
    if unknown:
        problems.append(f"{where}: unknown 'requires' keys: {', '.join(sorted(unknown))}")
    parsed = {}
    for key in _REQUIRES_KEYS & set(requires):
        if not _is_string_list(requires[key]):
            problems.append(f"{where}: 'requires.{key}' must be a list of strings")
        else:
            parsed[key] = tuple(requires[key])
    return parsed


def _check_compose_targets(entries: list[Entry], problems: list[str]) -> None:
    for entry in entries:
        if entry.method != "compose":
            continue
        for target in entry.targets:
            if target.startswith(("~/.agents/skills/", "~/.claude/skills/")):
                problems.append(f"entry '{entry.id}': compose writes a file and cannot target the skill folder {target}")


def _check_protected_targets(entries: list[Entry], external: list[str], problems: list[str]) -> None:
    external_names = {name.lower() for name in external}
    for entry in entries:
        for target in entry.targets:
            folder, _, name = target.rpartition("/")
            if folder not in ("~/.agents/skills", "~/.claude/skills"):
                continue
            if target.lower() == "~/.claude/skills/synced":
                problems.append(f"entry '{entry.id}': {target} is reserved for cloud-synced skills")
            elif name.lower() in external_names:
                problems.append(f"entry '{entry.id}': {target} is an external skill and is app-managed")


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_repo_relative(path: str) -> bool:
    pure = PurePosixPath(path)
    return str(pure) == path and path != "." and not pure.is_absolute() and ".." not in pure.parts


def _check_unique(values: list[str], label: str, problems: list[str]) -> None:
    seen: set[str] = set()
    for value in values:
        key = value.lower()
        if key in seen:
            problems.append(f"duplicate {label}: {value}")
        seen.add(key)
