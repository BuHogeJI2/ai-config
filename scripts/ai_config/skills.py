from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .paths import Environment

_FIELD = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")
_SKIPPED_DIRS = {".git", ".trash", "node_modules"}


@dataclass(frozen=True)
class LocalSkill:
    agent: str
    kind: str
    path: Path
    declared_name: str | None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def names(self) -> set[str]:
        """Lower-case directory and declared names, because the default macOS file system ignores case."""
        return {name.lower() for name in (self.name, self.declared_name) if name}


def read_frontmatter(skill_md: Path) -> dict[str, str] | None:
    """Return the top-level `key: value` fields of a SKILL.md frontmatter block, or None if there is none.

    Nested YAML is not parsed; a block value such as `description: >` is returned as its marker.
    """
    lines = skill_md.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        match = _FIELD.match(line)
        if match:
            fields[match.group(1)] = _unquote(match.group(2).strip())
    return None


def discover(env: Environment) -> list[LocalSkill]:
    skills: list[LocalSkill] = []
    skills += _children("codex", "personal", env.codex_skills)
    skills += _children("codex", "legacy", env.codex_legacy_skills)
    skills += _children("codex", "system", env.codex_legacy_skills / ".system")
    skills += _plugin_skills("codex", env.codex_home / "plugins" / "cache")
    skills += _children("claude", "personal", env.claude_skills)
    for bucket in _subdirectories(env.claude_skills / "synced"):
        skills += _children("claude", "synced", bucket)
    skills += _plugin_skills("claude", env.claude_home / "plugins" / "cache")
    skills += _plugin_skills("claude", env.claude_home / "plugins" / "synced")
    return skills


def _children(agent: str, kind: str, root: Path) -> list[LocalSkill]:
    return [
        _local_skill(agent, kind, directory)
        for directory in _subdirectories(root)
        if (directory / "SKILL.md").is_file()
    ]


def _plugin_skills(agent: str, root: Path) -> list[LocalSkill]:
    skills: list[LocalSkill] = []
    for current, dirs, _ in os.walk(root):
        if Path(current).name == "skills":
            skills += _children(agent, "plugin", Path(current))
            dirs.clear()
        else:
            dirs[:] = [name for name in dirs if name not in _SKIPPED_DIRS]
    return skills


def _subdirectories(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(entry for entry in root.iterdir() if not entry.name.startswith(".") and entry.is_dir())


def _local_skill(agent: str, kind: str, directory: Path) -> LocalSkill:
    fields = read_frontmatter(directory / "SKILL.md") or {}
    return LocalSkill(agent=agent, kind=kind, path=directory, declared_name=fields.get("name"))


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value
