from __future__ import annotations

import errno
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .content import scan_tree
from .fileops import TargetChangedError, remove_path, temporary_sibling, write_text_file
from .manifest import OWNERS, ManifestError, is_manageable_name, parse_manifest, skill_targets
from .paths import Environment, is_below
from .planner import effective_location, points_into
from .trees import IGNORED_NAMES, TreeError, identical, signature, snapshot

AGENTS = ("codex", "claude")


class AdoptError(Exception):
    pass


@dataclass(frozen=True)
class AdoptResult:
    local: Path
    source: str
    entry_id: str
    entry_added: bool
    replaced_repo_copy: bool


def adopt(
    repo_root: Path, env: Environment, agent: str, name: str, owner: str, replace_repo: bool = False
) -> AdoptResult:
    """Copy a local skill into `<owner>/skills/<name>` and add its manifest entry.

    Only the repository working tree changes; agent homes are never touched and nothing is committed.
    The copied bytes are the validated bytes, and the destination and manifest are checked again right
    before they change. On failure the repository is put back as it was.
    """
    if agent not in AGENTS or owner not in OWNERS or owner not in (agent, "shared"):
        raise AdoptError(f"a {agent} skill can be adopted into '{agent}' or 'shared', not '{owner}'")
    if not is_manageable_name(name):
        raise AdoptError(f"'{name}' is not a valid skill name")
    repo_root = repo_root.resolve()
    manifest_path = repo_root / "manifest.json"
    manifest_text, raw = _load_raw_manifest(manifest_path)
    manifest = parse_manifest(raw)
    if manifest.is_external(name):
        raise AdoptError(f"'{name}' is an external, app-managed skill")

    source = f"{owner}/skills/{name}"
    new_raw, entry_id, entry_added = _prospective_manifest(raw, manifest, source, owner, name)

    local = _find_local_copy(env, agent, name, repo_root)
    validated = _validate_tree(local)

    destination = repo_root / source
    if not is_below(destination.parent.resolve(), repo_root):
        raise AdoptError(f"{owner}/skills resolves outside the repository")
    location = effective_location(destination)
    before = _snapshot_or_fail(destination)
    replacing = before != ("missing",)
    if replacing and not replace_repo:
        raise AdoptError(f"{source} already exists; use --replace-repo to overwrite it with the local copy")

    def destination_unchanged() -> bool:
        try:
            return (
                effective_location(destination) == location
                and is_below(location.parent.resolve(), repo_root)
                and snapshot(destination) == before
            )
        except TreeError:
            return False

    manifest_location = effective_location(manifest_path)

    def manifest_unchanged() -> bool:
        try:
            return (
                effective_location(manifest_path) == manifest_location
                and manifest_path.read_text(encoding="utf-8") == manifest_text
            )
        except OSError:
            return False

    def placed_copy_intact() -> bool:
        return effective_location(destination) == location and _signature_or_none(location) == validated

    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = temporary_sibling(location)
    aside = None
    placed = False
    try:
        shutil.copytree(local, staged, symlinks=True, ignore=shutil.ignore_patterns(*IGNORED_NAMES))
        if _signature_or_none(local) != validated:
            raise TargetChangedError(f"{local} changed while it was copied")
        if _validate_tree(staged) != validated:
            raise TargetChangedError(f"the copy of {local} differs from the validated content")
        if not (destination_unchanged() and manifest_unchanged()):
            raise TargetChangedError(f"{source} or manifest.json changed while adopting")
        if replacing:
            aside = temporary_sibling(location)
            os.rename(location, aside)
        if os.path.lexists(destination) or effective_location(destination) != location:
            raise TargetChangedError(f"{source} changed while adopting")
        os.rename(staged, location)
        placed = True
        if entry_added:
            write_text_file(
                manifest_path,
                json.dumps(new_raw, indent=2) + "\n",
                unchanged=lambda: manifest_unchanged() and placed_copy_intact(),
            )
    except BaseException as error:
        _roll_back(destination, location, repo_root, staged, aside, placed, validated)
        if isinstance(error, (OSError, TreeError)) and not isinstance(error, TargetChangedError):
            raise AdoptError(f"adopt failed and was rolled back: {error}") from error
        raise
    if aside is not None:
        remove_path(aside)
    return AdoptResult(local, source, entry_id, entry_added, replacing)


def _load_raw_manifest(path: Path) -> tuple[str, dict]:
    try:
        text = path.read_text(encoding="utf-8")
        raw = json.loads(text)
        parse_manifest(raw)
    except (OSError, json.JSONDecodeError, ManifestError) as error:
        raise AdoptError(f"manifest.json is not valid; run doctor first ({error})")
    return text, raw


def _prospective_manifest(raw: dict, manifest, source: str, owner: str, name: str) -> tuple[dict, str, bool]:
    """Return the manifest as it will be after adopting, validated before anything is copied."""
    targets = list(skill_targets(owner, name))
    entry = manifest.entry_for_source(source)
    if entry is not None:
        if entry.method != "symlink" or entry.sources != (source,) or set(entry.targets) != set(targets):
            raise AdoptError(f"manifest entry '{entry.id}' does not match {source}; fix it by hand first")
        return raw, entry.id, False
    used_ids = {existing.id for existing in manifest.entries}
    entry_id = next((candidate for candidate in (f"skill/{name}", f"skill/{owner}/{name}") if candidate not in used_ids), None)
    if entry_id is None:
        raise AdoptError(f"manifest entry ids skill/{name} and skill/{owner}/{name} are both used")
    new_raw = json.loads(json.dumps(raw))
    new_raw.setdefault("entries", []).append({"id": entry_id, "method": "symlink", "source": source, "targets": targets})
    try:
        parse_manifest(new_raw)
    except ManifestError as error:
        raise AdoptError(f"the manifest would become invalid: {'; '.join(error.problems)}")
    return new_raw, entry_id, True


def _find_local_copy(env: Environment, agent: str, name: str, repo_root: Path) -> Path:
    if agent == "codex":
        candidates = [env.codex_skills / name]
        if env.codex_legacy_skills_are_separate:
            candidates.append(env.codex_legacy_skills / name)
    else:
        candidates = [env.claude_skills / name]
    found = [path for path in candidates if os.path.lexists(path)]
    if not found:
        raise AdoptError(f"no local {agent} skill '{name}' in {', '.join(env.shorten(path) for path in candidates)}")
    for path in found:
        if points_into(path, repo_root):
            raise AdoptError(f"{env.shorten(path)} is already a link into this repository")
        if path.is_symlink():
            raise AdoptError(f"{env.shorten(path)} is a link; adopt the real folder it points to instead")
        if not path.is_dir():
            raise AdoptError(f"{env.shorten(path)} is not a folder")
    if len(found) > 1:
        try:
            same = identical(found[0], found[1])
        except TreeError as error:
            raise AdoptError(str(error))
        if not same:
            raise AdoptError(
                f"{env.shorten(found[0])} and {env.shorten(found[1])} differ; make them equal or remove one first"
            )
    return found[0]


def _validate_tree(root: Path) -> dict:
    """Check a skill tree and return its signature; the same checks run on the local copy and the staged copy."""
    try:
        tree = signature(root)
    except TreeError as error:
        raise AdoptError(str(error))
    if tree.get("SKILL.md", ("missing",))[0] != "file":
        raise AdoptError(f"{root} has no SKILL.md")
    real_root = Path(os.path.realpath(root))
    for relative, entry in tree.items():
        if entry[0] != "link":
            continue
        link = root / relative
        try:
            os.stat(link)
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise AdoptError(f"{link} is part of a link loop")
        if not is_below(Path(os.path.realpath(link)), real_root):
            raise AdoptError(f"{link} links outside the skill folder: {entry[1]}")
    problems = scan_tree(root, check_home_paths=lambda relative: True)
    if problems:
        raise AdoptError("refusing to adopt: " + "; ".join(str(problem) for problem in problems))
    return tree


def _signature_or_none(path: Path) -> dict | None:
    try:
        return signature(path)
    except TreeError:
        return None


def _snapshot_or_fail(path: Path) -> tuple:
    try:
        return snapshot(path)
    except TreeError as error:
        raise AdoptError(str(error))


def _roll_back(
    destination: Path,
    location: Path,
    repo_root: Path,
    staged: Path,
    aside: Path | None,
    placed: bool,
    validated: dict,
) -> None:
    """Undo a failed adopt, touching only the real paths captured before copying.

    If the owner folder was moved or redirected meanwhile, nothing is changed and the recovery
    paths are reported instead, because they may no longer mean what they meant.
    """
    if effective_location(destination) != location or not is_below(location.parent.resolve(), repo_root):
        kept = ", ".join(str(path) for path in (staged, aside, location) if path is not None)
        raise AdoptError(f"the repository folder changed during adopt; nothing was rolled back, check {kept}")
    if placed and _signature_or_none(location) == validated:
        os.rename(location, staged)
    if os.path.lexists(staged):
        remove_path(staged)
    if aside is not None:
        if os.path.lexists(location):
            raise AdoptError(f"{location} was created by someone else; the previous copy is kept at {aside}")
        os.rename(aside, location)
