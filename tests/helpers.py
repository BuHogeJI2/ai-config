from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ai_config.paths import Environment


class FakeWorldTestCase(unittest.TestCase):
    """Gives each test an empty fake home folder and an empty fake repository."""

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve()
        self.home = root / "home"
        self.repo = root / "repo"
        self.home.mkdir()
        self.repo.mkdir()
        self.env = Environment.from_env({"HOME": str(self.home)})
        self.write_manifest()

    def write_manifest(self, entries: list[dict] | None = None, external: list[str] | None = None) -> None:
        data = {"version": 1, "external": external or [], "entries": entries or []}
        self.write(self.repo / "manifest.json", json.dumps(data))

    def add_skill(self, parent: Path, name: str, declared_name: str | None = None, description: str = "Test skill.") -> Path:
        directory = parent / name
        self.write(directory / "SKILL.md", f"---\nname: {declared_name or name}\ndescription: {description}\n---\n\nBody.\n")
        return directory

    def link(self, link: Path, target: Path) -> None:
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)

    @staticmethod
    def write(path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path
