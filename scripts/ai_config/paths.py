from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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
    def claude_skills(self) -> Path:
        return self.claude_home / "skills"

    def expand(self, target: str) -> Path:
        if not target.startswith("~/"):
            raise ValueError(f"target must start with '~/': {target}")
        return self.home / target[2:]

    def shorten(self, path: Path) -> str:
        try:
            return "~/" + str(path.relative_to(self.home))
        except ValueError:
            return str(path)
