from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from .agents import AGENTS, target_agent
from .compose import ComposeError, compose, text_hash
from .manifest import Entry, Manifest, is_manageable_name
from .paths import Environment, is_below
from .state import State
from .trees import TreeError, file_snapshot, read_regular_file, signature, snapshot

CREATE = "create"
KEEP = "ok"
REPLACE = "replace"
REGENERATE = "regenerate"
RELINK = "relink"
REMOVE_LEGACY = "remove-legacy"
ORPHAN = "orphan"
PRUNE = "prune"
CONFLICT = "conflict"

CHANGES = (CREATE, REPLACE, REGENERATE, RELINK, REMOVE_LEGACY, PRUNE)
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
    output: str | None = None
    source_hashes: dict[str, str] | None = None


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
    agents: tuple[str, ...] = AGENTS,
) -> Plan:
    """Plan every manifest target of the selected agents, the legacy Codex copies, and the orphan links.

    `prune` turns orphans into removals. Entries named in `replace_local` replace local content that
    differs from the repository instead of reporting a conflict; unsafe conflicts stay conflicts.
    Targets of the other agents are never installed; what this tool put there becomes an orphan.
    """
    repo_root = repo_root.resolve()
    state = state or State()
    claims = _Claims(repo_root)
    orphan_kind = PRUNE if prune else ORPHAN
    actions: list[Action] = []
    legacy: list[tuple[Entry, Path, Path]] = []
    disabled: list[tuple[Path, str]] = []
    for entry in manifest.entries:
        for target in entry.targets:
            path = env.expand(target)
            agent = target_agent(target)
            if agent not in agents:
                disabled.append((path, agent))
                continue
            actions += _plan_target(entry, path, repo_root, claims, state, entry.id in replace_local)
            if path.parent == env.codex_skills and env.codex_legacy_skills_are_separate:
                legacy.append((entry, repo_root / entry.sources[0], env.codex_legacy_skills / path.name))
    for entry, source, legacy_path in legacy:
        actions += _plan_legacy_copy(entry, source, legacy_path, claims, entry.id in replace_local)
    for path, agent in disabled:
        actions += _plan_disabled_target(path, agent, repo_root, claims, state, orphan_kind)
    actions += _find_orphans(repo_root, env, manifest, claims, state, orphan_kind)
    return Plan(tuple(actions))


class _Claims:
    """Tracks the real locations the plan may change, so no location is changed twice or inside the repository.

    The location recorded by a successful claim is the one every later check of that target uses.
    """

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.owners: dict[Path, Path] = {}
        self.locations: dict[Path, Path] = {}

    def claim(self, path: Path) -> str | None:
        location = effective_location(path)
        if is_below(location, self.repo_root):
            return f"location resolves into the repository: {location}"
        if location in self.owners:
            return f"same location as {self.owners[location]}"
        self.owners[location] = path
        self.locations[path] = location
        return None

    def is_claimed(self, path: Path) -> bool:
        return effective_location(path) in self.owners


def link_destination(link: Path) -> Path:
    """Return the absolute, normalized path a symlink names, without requiring it to exist."""
    return _destination(link, os.readlink(link))


def points_into(link: Path, repo_root: Path) -> bool:
    return link.is_symlink() and is_below(link_destination(link), repo_root.resolve())


def is_link_from_moved_checkout(link: Path, state: State, repo_root: Path) -> bool:
    """True when the state file records `link` with its current text, and it points into the checkout it came from."""
    return link.is_symlink() and _is_recorded_old_link(link, os.readlink(link), state, repo_root)


def effective_location(path: Path) -> Path:
    """Return where `path` really is: its parent with symlinks resolved, and its own name unresolved."""
    return path.parent.resolve() / path.name


def _destination(link: Path, text: str) -> Path:
    return Path(os.path.normpath(link.parent / text))


def _is_recorded_old_link(link: Path, text: str, state: State, repo_root: Path) -> bool:
    record = state.links.get(link)
    return (
        record is not None
        and record.repo_root != repo_root
        and text == record.link_text
        and is_below(_destination(link, text), record.repo_root)
    )


def _capture(target: Path) -> tuple[tuple | None, str]:
    """Snapshot `target`, or return None and the reason it cannot be read."""
    try:
        return snapshot(target), ""
    except TreeError as error:
        return None, str(error)


def _captured_file_hash(captured: tuple) -> str | None:
    """The sha256 of a captured regular file, or None for anything else."""
    if captured[0] != "tree" or len(captured[1]) != 1:
        return None
    relative, entry = captured[1][0]
    return entry[1] if relative == "." and entry[0] == "file" else None


def _plan_target(
    entry: Entry, target: Path, repo_root: Path, claims: _Claims, state: State, forced: bool
) -> list[Action]:
    source = repo_root / entry.sources[0]
    problem = claims.claim(target)
    if problem:
        return [Action(CONFLICT, target, entry.id, source, f"target {problem}")]
    location = claims.locations[target]
    captured, problem = _capture(target)
    if captured is None:
        return [Action(CONFLICT, target, entry.id, source, f"cannot read: {problem}")]
    if entry.method == "compose":
        return [_plan_compose(entry, target, repo_root, state, forced, location, captured)]
    return [_plan_link(entry, source, target, repo_root, state, forced, location, captured)]


def _plan_compose(
    entry: Entry, target: Path, repo_root: Path, state: State, forced: bool, location: Path, captured: tuple
) -> Action:
    try:
        composition = compose(repo_root, entry.sources)
    except ComposeError as error:
        return Action(CONFLICT, target, entry.id, detail=str(error))
    output = composition.output

    def action(kind: str, detail: str = "") -> Action:
        return _action(kind, target, entry.id, None, detail, output, composition.source_hashes, captured, location)

    if captured == ("missing",):
        return action(CREATE)
    if captured[0] == "link":
        if is_below(_destination(target, captured[1]), repo_root) or _is_recorded_old_link(
            target, captured[1], state, repo_root
        ):
            return action(REPLACE, "managed link is replaced by the generated file; backed up first")
        if forced:
            return action(REPLACE, f"link {_REPLACED_LOCAL}")
        return action(CONFLICT, "is a link; a generated file must be a regular file")
    current_hash = _captured_file_hash(captured)
    if current_hash is None:
        return action(CONFLICT, "is not a regular file")
    if current_hash == text_hash(output):
        return action(KEEP)
    record = state.generated.get(target)
    if record is not None and current_hash in record.owned_hashes:
        return action(REGENERATE, "sources changed since the last install; backed up first")
    if forced:
        return action(REPLACE, f"local content {_REPLACED_LOCAL}")
    if record is not None and not record.pending:
        return action(CONFLICT, "was edited since it was generated; move the edit into a source, or use --replace-local")
    try:
        data, info = read_regular_file(target)
    except TreeError as error:
        return action(CONFLICT, str(error))
    if file_snapshot(data, info) != captured:
        return action(CONFLICT, "changed while planning")
    text = _decoded(data)
    if text is None:
        return action(CONFLICT, "local content is not UTF-8 text")
    if text.strip("\n") == composition.body.strip("\n"):
        return action(REPLACE, "local file equals the generated content without the marker; backed up first")
    return action(CONFLICT, "local content differs from the generated output")


def _decoded(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _plan_link(
    entry: Entry,
    source: Path,
    target: Path,
    repo_root: Path,
    state: State,
    forced: bool,
    location: Path,
    captured: tuple,
) -> Action:
    def action(kind: str, detail: str = "") -> Action:
        return _action(kind, target, entry.id, source, detail, expected=captured, location=location)

    if not source.exists():
        return action(CONFLICT, "repository source does not exist")
    if not is_below(source.resolve(), repo_root):
        return action(CONFLICT, f"repository source resolves outside the repository: {source.resolve()}")
    if captured == ("missing",):
        return action(CREATE)
    if captured[0] == "link":
        destination = _destination(target, captured[1])
        if destination == source:
            return action(KEEP)
        if is_below(destination, repo_root):
            return action(RELINK, f"link points to another repository path: {destination}")
        if _is_recorded_old_link(target, captured[1], state, repo_root):
            return action(RELINK, f"link still points into the old checkout {state.links[target].repo_root}")
        if forced:
            return action(REPLACE, f"link to {destination} {_REPLACED_LOCAL}")
        if not destination.exists():
            return action(CONFLICT, f"broken link to {destination}")
        return action(CONFLICT, f"link points outside this repository: {destination}")
    record = state.generated.get(target)
    current_hash = _captured_file_hash(captured)
    if record is not None and current_hash in record.owned_hashes:
        return action(REPLACE, "generated file is replaced by a link; backed up first")
    return _compare(
        action,
        source,
        captured,
        REPLACE,
        "local copy is identical and is backed up first",
        "local content differs from the repository",
        forced,
    )


def _plan_legacy_copy(entry: Entry, source: Path, legacy: Path, claims: _Claims, forced: bool) -> list[Action]:
    if not os.path.lexists(legacy):
        return []
    problem = claims.claim(legacy)
    if problem:
        return [Action(CONFLICT, legacy, entry.id, source, f"legacy Codex copy {problem}")]
    location = claims.locations[legacy]
    captured, problem = _capture(legacy)
    if captured is None:
        return [Action(CONFLICT, legacy, entry.id, source, f"cannot read the legacy Codex copy: {problem}")]

    def action(kind: str, detail: str = "") -> Action:
        return _action(kind, legacy, entry.id, source, detail, expected=captured, location=location)

    if captured == ("missing",):
        return []
    if captured[0] == "link":
        destination = _destination(legacy, captured[1])
        if destination == source:
            return [action(REMOVE_LEGACY, "legacy Codex link to the same source")]
        if forced:
            return [action(REMOVE_LEGACY, f"legacy Codex link to {destination} {_REPLACED_LOCAL}")]
        return [action(CONFLICT, f"legacy Codex link points to {destination}")]
    if not source.exists():
        return [action(CONFLICT, "repository source does not exist")]
    return [
        _compare(
            action,
            source,
            captured,
            REMOVE_LEGACY,
            "legacy Codex copy is identical and is backed up first",
            "legacy Codex copy differs from the repository",
            forced,
        )
    ]


def _action(
    kind: str,
    target: Path,
    entry_id: str | None,
    source: Path | None,
    detail: str,
    output: str | None = None,
    hashes: dict[str, str] | None = None,
    expected: tuple | None = None,
    location: Path | None = None,
) -> Action:
    """Build an action from a snapshot and a location captured before any decision was made from it.

    The location is checked once more here, so a parent redirected while planning is a conflict.
    """
    if kind == CONFLICT:
        return Action(kind, target, entry_id, source, detail)
    if expected is None or location is None:
        raise ValueError("a planned change needs its captured snapshot and location")
    if effective_location(target) != location:
        return Action(CONFLICT, target, entry_id, source, "its location changed while planning")
    return Action(kind, target, entry_id, source, detail, location, expected, output, hashes)


def _compare(
    action, source: Path, captured: tuple, same_kind: str, same_detail: str, different_detail: str, forced: bool
) -> Action:
    try:
        same = ("tree", tuple(sorted(signature(source).items()))) == captured
    except TreeError as error:
        return action(CONFLICT, f"cannot compare: {error}")
    if same:
        return action(same_kind, same_detail)
    if forced:
        return action(same_kind, f"{different_detail}; {_REPLACED_LOCAL}")
    return action(CONFLICT, different_detail)


def _plan_disabled_target(
    target: Path, agent: str, repo_root: Path, claims: _Claims, state: State, kind: str
) -> list[Action]:
    """Offer to remove what this tool put at the target of a disabled agent; leave everything else alone.

    A location already claimed, such as a folder shared with an enabled target, is never touched.
    """
    if not os.path.lexists(target) or claims.is_claimed(target) or claims.claim(target) is not None:
        return []
    location = claims.locations[target]
    detail = f"agent disabled: {agent}"
    captured, _ = _capture(target)
    if captured is not None and captured[0] == "link":
        if is_below(_destination(target, captured[1]), repo_root) or _is_recorded_old_link(
            target, captured[1], state, repo_root
        ):
            return [_action(kind, target, None, None, detail, expected=captured, location=location)]
        return []
    owned = owned_generated_snapshot(target, state)
    if owned is not None:
        return [_action(kind, target, None, None, detail, expected=owned, location=location)]
    return []


def _find_orphans(
    repo_root: Path, env: Environment, manifest: Manifest, claims: _Claims, state: State, kind: str
) -> list[Action]:
    orphans = []
    for link in _orphan_candidates(env, manifest):
        if not link.is_symlink() or claims.is_claimed(link) or claims.claim(link) is not None:
            continue
        location = claims.locations[link]
        captured, _ = _capture(link)
        if captured is None or captured[0] != "link":
            continue
        destination = _destination(link, captured[1])
        if is_below(destination, repo_root) or _is_recorded_old_link(link, captured[1], state, repo_root):
            orphans.append(
                _action(
                    kind,
                    link,
                    None,
                    None,
                    f"link into this repository has no manifest entry: {destination}",
                    expected=captured,
                    location=location,
                )
            )
    for target in sorted(state.generated):
        if claims.is_claimed(target) or claims.claim(target) is not None:
            continue
        location = claims.locations[target]
        owned = owned_generated_snapshot(target, state)
        if owned is not None:
            orphans.append(
                _action(kind, target, None, None, "generated file has no manifest entry", expected=owned, location=location)
            )
    return orphans


def owned_generated_snapshot(target: Path, state: State) -> tuple | None:
    """Return the snapshot of a generated file that is ours, taken from the same bytes that prove it.

    Ours means a regular, non-link file whose sha256 equals a recorded output hash. Callers use this
    snapshot as the expected state, so a file changed after this read is never mistaken for ours.
    """
    record = state.generated.get(target)
    if record is None:
        return None
    try:
        data, info = read_regular_file(target)
    except TreeError:
        return None
    if hashlib.sha256(data).hexdigest() not in record.owned_hashes:
        return None
    return file_snapshot(data, info)


def is_unedited_generated_file(target: Path, state: State) -> bool:
    return owned_generated_snapshot(target, state) is not None


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
