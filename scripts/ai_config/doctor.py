from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .manifest import OWNERS, Manifest, ManifestError, load_manifest, skill_targets
from .paths import Environment
from .planner import CHANGES, CONFLICT, ORPHAN, build_plan, points_into
from .skills import LocalSkill, discover, read_frontmatter
from .state import State, StateError, load_state

ERROR = "error"
WARNING = "warning"
INFO = "info"
LEVELS = (ERROR, WARNING, INFO)

_SKIPPED_REPO_DIRS = {".git", "__pycache__"}
_FORBIDDEN_NAMES = {
    ".env",
    ".claude.json",
    ".credentials.json",
    "auth.json",
    "credentials.json",
    "default.rules",
    "history.jsonl",
}
_FORBIDDEN_SUFFIXES = (".db", ".log", ".sqlite", ".sqlite3")
_SECRET_PATTERNS = (
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("API key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
)
_HOME_PATH = re.compile(r"(?<![\w.~-])/(?:Users|home)/[A-Za-z0-9._-]+")
_MAX_SCANNED_BYTES = 1_000_000


@dataclass(frozen=True)
class Finding:
    level: str
    message: str


def run_doctor(repo_root: Path, env: Environment) -> list[Finding]:
    findings: list[Finding] = []
    try:
        manifest = load_manifest(repo_root / "manifest.json")
    except ManifestError as error:
        findings += [Finding(ERROR, f"manifest: {problem}") for problem in error.problems]
        manifest = Manifest(external=(), entries=())

    state, state_findings = _check_state(repo_root, env)
    findings += state_findings
    local_skills = discover(env)
    findings += _check_entries(repo_root, manifest)
    findings += _check_repo_skills(repo_root, manifest)
    findings += _check_duplicates(local_skills, env)
    findings += _check_local_skills(local_skills, manifest, repo_root, env)
    findings += _check_install_plan(repo_root, env, manifest, state)
    findings += _check_repo_content(repo_root)
    return findings


def _check_entries(repo_root: Path, manifest: Manifest) -> list[Finding]:
    findings = []
    for entry in manifest.entries:
        for source in entry.sources:
            if not (repo_root / source).exists():
                findings.append(Finding(ERROR, f"entry '{entry.id}': source does not exist: {source}"))
            owner_and_name = _skill_source(source)
            if not owner_and_name:
                continue
            if entry.method != "symlink":
                findings.append(Finding(ERROR, f"entry '{entry.id}': skills must use the symlink method"))
            expected = skill_targets(*owner_and_name)
            if set(entry.targets) != set(expected):
                findings.append(
                    Finding(ERROR, f"entry '{entry.id}': targets must be {', '.join(expected)} for {source}")
                )
    return findings


def _check_repo_skills(repo_root: Path, manifest: Manifest) -> list[Finding]:
    findings = []
    for owner in OWNERS:
        skills_dir = repo_root / owner / "skills"
        if not skills_dir.is_dir():
            continue
        for directory in sorted(path for path in skills_dir.iterdir() if path.is_dir()):
            source = f"{owner}/skills/{directory.name}"
            if manifest.is_external(directory.name):
                findings.append(Finding(ERROR, f"{source}: external skills must not be in the repository"))
            if not manifest.entry_for_source(source):
                findings.append(Finding(ERROR, f"{source}: skill has no manifest entry"))
            findings += _check_skill_metadata(directory, source)
    return findings


def _check_skill_metadata(directory: Path, source: str) -> list[Finding]:
    skill_md = directory / "SKILL.md"
    if not skill_md.is_file():
        return [Finding(ERROR, f"{source}: SKILL.md is missing")]
    fields = read_frontmatter(skill_md)
    if fields is None:
        return [Finding(ERROR, f"{source}: SKILL.md has no frontmatter")]
    findings = [
        Finding(ERROR, f"{source}: SKILL.md frontmatter has no '{key}'")
        for key in ("name", "description")
        if not fields.get(key)
    ]
    if fields.get("name") and fields["name"] != directory.name:
        findings.append(Finding(ERROR, f"{source}: SKILL.md name '{fields['name']}' differs from the folder name"))
    return findings


def _check_duplicates(skills: list[LocalSkill], env: Environment) -> list[Finding]:
    findings = []
    for agent in ("codex", "claude"):
        own = _group_by_name(skill for skill in skills if skill.agent == agent and skill.kind != "plugin")
        plugins = _group_by_name(skill for skill in skills if skill.agent == agent and skill.kind == "plugin")
        reported: set[frozenset[Path]] = set()
        for name, group in sorted(own.items()):
            paths = frozenset(skill.path for skill in group)
            if len(paths) > 1 and paths not in reported:
                reported.add(paths)
                findings.append(Finding(ERROR, f"duplicate {agent} skill '{name}': {_list_paths(paths, env)}"))
        for name in sorted(own.keys() & plugins.keys()):
            paths = [skill.path for skill in own[name] + plugins[name]]
            findings.append(Finding(WARNING, f"{agent} skill '{name}' is also a plugin skill: {_list_paths(paths, env)}"))
    return findings


def _check_local_skills(
    skills: list[LocalSkill], manifest: Manifest, repo_root: Path, env: Environment
) -> list[Finding]:
    findings = []
    for skill in skills:
        if skill.kind not in ("personal", "legacy"):
            continue
        shown = env.shorten(skill.path)
        links_into_repo = points_into(skill.path, repo_root)
        if manifest.is_external(skill.name):
            if links_into_repo:
                findings.append(Finding(WARNING, f"external {skill.agent} skill links into this repository: {shown}"))
            else:
                findings.append(Finding(INFO, f"external {skill.agent} skill: {shown}"))
        elif not links_into_repo:
            findings.append(Finding(INFO, f"unmanaged {skill.agent} skill: {shown}"))
    return findings


def _check_state(repo_root: Path, env: Environment) -> tuple[State, list[Finding]]:
    try:
        state = load_state(env.state_dir)
    except StateError as error:
        return State(), [Finding(ERROR, f"state: {error}")]
    findings = []
    for target, record in sorted(state.links.items()):
        if not target.is_symlink() or os.readlink(target) != record.link_text:
            findings.append(Finding(WARNING, f"state: recorded link was changed or removed: {env.shorten(target)}"))
        elif record.repo_root != repo_root.resolve():
            findings.append(
                Finding(WARNING, f"state: {env.shorten(target)} points into another checkout {record.repo_root}; install relinks it")
            )
    return state, findings


def _check_install_plan(repo_root: Path, env: Environment, manifest: Manifest, state: State) -> list[Finding]:
    findings = []
    for action in build_plan(repo_root, env, manifest, state).actions:
        shown = env.shorten(action.target)
        if action.kind == CONFLICT:
            findings.append(Finding(ERROR, f"install conflict at {shown}: {action.detail}"))
        elif action.kind == ORPHAN:
            findings.append(Finding(WARNING, f"orphan link {shown}: {action.detail}"))
        elif action.kind in CHANGES:
            findings.append(Finding(INFO, f"install pending ({action.kind}) at {shown}"))
    return findings


def _check_repo_content(repo_root: Path) -> list[Finding]:
    findings = []
    for current, dirs, files in os.walk(repo_root):
        dirs[:] = sorted(name for name in dirs if name not in _SKIPPED_REPO_DIRS)
        for name in sorted(files):
            path = Path(current) / name
            relative = path.relative_to(repo_root).as_posix()
            if _is_forbidden(name):
                findings.append(Finding(ERROR, f"{relative}: forbidden file in the repository"))
                continue
            text = _read_text(path)
            if text is not None:
                findings += _scan_text(relative, text, check_home_paths=relative.split("/")[0] in OWNERS)
    return findings


def _scan_text(relative: str, text: str, check_home_paths: bool) -> list[Finding]:
    findings = []
    for number, line in enumerate(text.splitlines(), start=1):
        for label, pattern in _SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(Finding(ERROR, f"{relative}:{number}: possible {label}"))
        if check_home_paths:
            match = _HOME_PATH.search(line)
            if match:
                findings.append(Finding(ERROR, f"{relative}:{number}: absolute home path {match.group(0)}"))
    return findings


def _is_forbidden(name: str) -> bool:
    if name.startswith(".env.") and name != ".env.example":
        return True
    return name in _FORBIDDEN_NAMES or name.endswith(_FORBIDDEN_SUFFIXES)


def _read_text(path: Path) -> str | None:
    if path.is_symlink() or path.stat().st_size > _MAX_SCANNED_BYTES:
        return None
    data = path.read_bytes()
    if b"\0" in data:
        return None
    return data.decode("utf-8", errors="replace")


def _skill_source(source: str) -> tuple[str, str] | None:
    parts = PurePosixPath(source).parts
    if len(parts) == 3 and parts[0] in OWNERS and parts[1] == "skills":
        return parts[0], parts[2]
    return None


def _group_by_name(skills) -> dict[str, list[LocalSkill]]:
    groups: dict[str, list[LocalSkill]] = defaultdict(list)
    for skill in skills:
        for name in skill.names:
            groups[name].append(skill)
    return groups


def _list_paths(paths, env: Environment) -> str:
    return ", ".join(sorted(env.shorten(path) for path in paths))
