from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .manifest import Entry, Manifest, is_manageable_name
from .paths import Environment, is_below
from .state import State
from .trees import TreeError, identical, snapshot

CREATE = "create"
KEEP = "ok"
REPLACE = "replace"
RELINK = "relink"
REMOVE_LEGACY = "remove-legacy"
ORPHAN = "orphan"
PRUNE = "prune"
CONFLICT = "conflict"

CHANGES = (CREATE, REPLACE, RELINK, REMOVE_LEGACY, PRUNE)
_REPLACED_LOCAL = "replaced by the repository version (--replace-local); backed up first"


@dataclass(frozen=True)
class Action:
    """One planned step. Changes carry where the target really was and what it looked like when planned."""

    kind: str
    target: Path
    entry_id: str | None = None
    source: Path | None = None
    detail: str = ""
    location: Path | None = None
    expected: tuple | None = None


@dataclass(frozen=True)
class Plan:
    actions: tuple[Action, ...]

    @property
    def conflicts(self) -> list[Action]:
        return [action for action in self.actions if action.kind == CONFLICT]

    @property
    def changes(self) -> list[Action]:
        return [action for action in self.actions if action.kind in CHANGES]

    @property
    def orphans(self) -> list[Action]:
        return [action for action in self.actions if action.kind == ORPHAN]


def build_plan(
    repo_root: Path,
    env: Environment,
    manifest: Manifest,
    state: State | None = None,
    prune: bool = False,
    replace_local: frozenset[str] = frozenset(),
) -> Plan:
    """Plan every manifest target, the legacy Codex copies, and the orphan links.

    `prune` turns orphans into removals. Entries named in `replace_local` replace local content that
    differs from the repository instead of reporting a conflict; unsafe conflicts stay conflicts.
    """
    repo_root = repo_root.resolve()
    state = state or State()
    claims = _Claims(repo_root)
    actions: list[Action] = []
    legacy: list[tuple[Entry, Path, Path]] = []
    for entry in manifest.entries:
        for target in entry.targets:
            path = env.expand(target)
            actions += _plan_target(entry, path, repo_root, claims, state, entry.id in replace_local)
            if path.parent == env.codex_skills and env.codex_legacy_skills_are_separate:
                legacy.append((entry, repo_root / entry.sources[0], env.codex_legacy_skills / path.name))
    for entry, source, legacy_path in legacy:
        actions += _plan_legacy_copy(entry, source, legacy_path, claims, entry.id in replace_local)
    actions += _find_orphans(repo_root, env, manifest, claims, state, PRUNE if prune else ORPHAN)
    return Plan(tuple(actions))


class _Claims:
    """Tracks the real locations the plan may change, so no location is changed twice or inside the repository."""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.owners: dict[Path, Path] = {}

    def claim(self, path: Path) -> str | None:
        location = effective_location(path)
        if is_below(location, self.repo_root):
            return f"location resolves into the repository: {location}"
        if location in self.owners:
            return f"same location as {self.owners[location]}"
        self.owners[location] = path
        return None

    def is_claimed(self, path: Path) -> bool:
        return effective_location(path) in self.owners


def link_destination(link: Path) -> Path:
    """Return the absolute, normalized path a symlink names, without requiring it to exist."""
    text = os.readlink(link)
    return Path(os.path.normpath(link.parent / text))


def points_into(link: Path, repo_root: Path) -> bool:
    return link.is_symlink() and is_below(link_destination(link), repo_root.resolve())


def is_link_from_moved_checkout(link: Path, state: State, repo_root: Path) -> bool:
    """True when the state file records `link` with its current text, and it points into the checkout it came from."""
    record = state.links.get(link)
    return (
        record is not None
        and record.repo_root != repo_root
        and link.is_symlink()
        and os.readlink(link) == record.link_text
        and is_below(link_destination(link), record.repo_root)
    )


def effective_location(path: Path) -> Path:
    """Return where `path` really is: its parent with symlinks resolved, and its own name unresolved."""
    return path.parent.resolve() / path.name


def _plan_target(
    entry: Entry, target: Path, repo_root: Path, claims: _Claims, state: State, forced: bool
) -> list[Action]:
    source = repo_root / entry.sources[0]
    problem = claims.claim(target)
    if problem:
        return [Action(CONFLICT, target, entry.id, source, f"target {problem}")]
    if entry.method != "symlink":
        return [Action(CONFLICT, target, entry.id, detail=f"the {entry.method} method is not supported yet")]
    return [_plan_link(entry, source, target, repo_root, state, forced)]


def _plan_link(entry: Entry, source: Path, target: Path, repo_root: Path, state: State, forced: bool) -> Action:
    def action(kind: str, detail: str = "") -> Action:
        return _action(kind, target, entry.id, source, detail)

    if not source.exists():
        return action(CONFLICT, "repository source does not exist")
    if not is_below(source.resolve(), repo_root):
        return action(CONFLICT, f"repository source resolves outside the repository: {source.resolve()}")
    if target.is_symlink():
        destination = link_destination(target)
        if destination == source:
            return action(KEEP)
        if points_into(target, repo_root):
            return action(RELINK, f"link points to another repository path: {destination}")
        if is_link_from_moved_checkout(target, state, repo_root):
            return action(RELINK, f"link still points into the old checkout {state.links[target].repo_root}")
        if forced:
            return action(REPLACE, f"link to {destination} {_REPLACED_LOCAL}")
        if not target.exists():
            return action(CONFLICT, f"broken link to {destination}")
        return action(CONFLICT, f"link points outside this repository: {destination}")
    if not target.exists():
        return action(CREATE)
    return _compare(
        action,
        source,
        target,
        REPLACE,
        "local copy is identical and is backed up first",
        "local content differs from the repository",
        forced,
    )


def _plan_legacy_copy(entry: Entry, source: Path, legacy: Path, claims: _Claims, forced: bool) -> list[Action]:
    def action(kind: str, detail: str = "") -> Action:
        return _action(kind, legacy, entry.id, source, detail)

    if not os.path.lexists(legacy):
        return []
    problem = claims.claim(legacy)
    if problem:
        return [action(CONFLICT, f"legacy Codex copy {problem}")]
    if legacy.is_symlink():
        if link_destination(legacy) == source:
            return [action(REMOVE_LEGACY, "legacy Codex link to the same source")]
        if forced:
            return [action(REMOVE_LEGACY, f"legacy Codex link to {link_destination(legacy)} {_REPLACED_LOCAL}")]
        return [action(CONFLICT, f"legacy Codex link points to {link_destination(legacy)}")]
    if not legacy.exists():
        return []
    if not source.exists():
        return [action(CONFLICT, "repository source does not exist")]
    return [
        _compare(
            action,
            source,
            legacy,
            REMOVE_LEGACY,
            "legacy Codex copy is identical and is backed up first",
            "legacy Codex copy differs from the repository",
            forced,
        )
    ]


def _action(kind: str, target: Path, entry_id: str | None, source: Path | None, detail: str) -> Action:
    if kind == CONFLICT:
        return Action(kind, target, entry_id, source, detail)
    try:
        expected = snapshot(target)
    except TreeError as error:
        return Action(CONFLICT, target, entry_id, source, f"cannot read: {error}")
    return Action(kind, target, entry_id, source, detail, effective_location(target), expected)


def _compare(
    action, source: Path, local: Path, same_kind: str, same_detail: str, different_detail: str, forced: bool
) -> Action:
    try:
        same = identical(source, local)
    except TreeError as error:
        return action(CONFLICT, f"cannot compare: {error}")
    if same:
        return action(same_kind, same_detail)
    if forced:
        return action(same_kind, f"{different_detail}; {_REPLACED_LOCAL}")
    return action(CONFLICT, different_detail)


def _find_orphans(
    repo_root: Path, env: Environment, manifest: Manifest, claims: _Claims, state: State, kind: str
) -> list[Action]:
    orphans = []
    for link in _orphan_candidates(env, manifest):
        ours = points_into(link, repo_root) or is_link_from_moved_checkout(link, state, repo_root)
        if ours and not claims.is_claimed(link) and claims.claim(link) is None:
            orphans.append(
                _action(kind, link, None, None, f"link into this repository has no manifest entry: {link_destination(link)}")
            )
    return orphans


def _orphan_candidates(env: Environment, manifest: Manifest) -> list[Path]:
    """Return only paths that have a supported target shape; protected and external entries are never candidates."""
    candidates = [env.claude_home / "CLAUDE.md", env.codex_home / "AGENTS.md"]
    for folder, suffix in ((env.codex_skills, ""), (env.claude_skills, ""), (env.claude_home / "rules", ".md")):
        if not folder.is_dir():
            continue
        for child in sorted(folder.iterdir()):
            if (
                is_manageable_name(child.name)
                and child.name.endswith(suffix)
                and not (folder == env.claude_skills and child.name.lower() == "synced")
                and not manifest.is_external(child.name)
            ):
                candidates.append(child)
    return candidates
