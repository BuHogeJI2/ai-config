from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Environment:
    home: Path
    codex_home: Path
    state_dir: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Environment:
        home = Path(env["HOME"])
        codex_home = Path(env["CODEX_HOME"]) if env.get("CODEX_HOME") else home / ".codex"
        state_home = Path(env["XDG_STATE_HOME"]) if env.get("XDG_STATE_HOME") else home / ".local" / "state"
        return cls(home=home, codex_home=codex_home, state_dir=state_home / "ai-config")

    @property
    def claude_home(self) -> Path:
        return self.home / ".claude"

    @property
    def codex_skills(self) -> Path:
        return self.home / ".agents" / "skills"

    @property
    def codex_legacy_skills(self) -> Path:
        return self.codex_home / "skills"

    @property
    def codex_legacy_skills_are_separate(self) -> bool:
        return self.codex_legacy_skills.resolve() != self.codex_skills.resolve()

    @property
    def claude_skills(self) -> Path:
        return self.claude_home / "skills"

    def expand(self, target: str) -> Path:
        rest = PurePosixPath(target[2:])
        if not target.startswith("~/") or not rest.parts or rest.is_absolute() or ".." in rest.parts:
            raise ValueError(f"target must be a path below '~/': {target}")
        if rest.parts[0] == ".codex":
            return self.codex_home.joinpath(*rest.parts[1:])
        return self.home.joinpath(*rest.parts)

    def shorten(self, path: Path) -> str:
        if is_below(path, self.home):
            return "~/" + path.relative_to(self.home).as_posix()
        if is_below(path, self.codex_home):
            return "$CODEX_HOME/" + path.relative_to(self.codex_home).as_posix()
        return str(path)


def is_below(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
