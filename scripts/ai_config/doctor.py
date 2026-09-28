from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .content import scan_tree
from .manifest import OWNERS, Manifest, ManifestError, load_manifest, skill_targets
from .paths import Environment
from .planner import CHANGES, CONFLICT, ORPHAN, build_plan, points_into
from .runtime_checks import check_commands, check_mcp, check_skill_files, claude_mcp_inventory, codex_mcp_inventory
from .skills import LocalSkill, discover, read_frontmatter
from .state import State, StateError, load_state

ERROR = "error"
WARNING = "warning"
INFO = "info"
LEVELS = (ERROR, WARNING, INFO)

_SKIPPED_REPO_DIRS = {".git", "__pycache__"}


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
    findings += _check_runtime(repo_root, env, manifest)
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


def _check_runtime(repo_root: Path, env: Environment, manifest: Manifest) -> list[Finding]:
    problems = []
    inventories = None
    for entry in manifest.entries:
        problems += check_commands(entry)
        if entry.requires.get("mcp"):
            inventories = inventories or {"codex": codex_mcp_inventory(env), "claude": claude_mcp_inventory(env)}
            problems += check_mcp(entry, inventories)
        for source in entry.sources:
            if _skill_source(source) and (repo_root / source).is_dir():
                problems += check_skill_files(repo_root / source, source)
    return [Finding(problem.level, problem.message) for problem in problems]


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
    problems = scan_tree(
        repo_root,
        check_home_paths=lambda relative: relative.split("/")[0] in OWNERS,
        skipped_dirs=frozenset(_SKIPPED_REPO_DIRS),
    )
    return [
        Finding(ERROR, f"{problem.relative}: forbidden file in the repository")
        if problem.line is None
        else Finding(ERROR, str(problem))
        for problem in problems
    ]


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
