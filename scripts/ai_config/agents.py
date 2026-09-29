from __future__ import annotations

from typing import Iterable, Optional

CODEX = "codex"
CLAUDE = "claude"
AGENTS = (CODEX, CLAUDE)

SAVED = "saved"
DEFAULT = "default"
TEMPORARY = "temporary"


class AgentsError(Exception):
    pass


def target_agent(target: str) -> str:
    """Return the agent of a manifest target, read from its text before `~` or `CODEX_HOME` is expanded."""
    if target.startswith("~/.claude/"):
        return CLAUDE
    if target.startswith("~/.agents/") or target.startswith("~/.codex/"):
        return CODEX
    raise ValueError(f"target belongs to no agent: {target}")


def canonical(agents: Iterable[str]) -> tuple[str, ...]:
    chosen = set(agents)
    return tuple(agent for agent in AGENTS if agent in chosen)


def parse_agents(value: str) -> tuple[str, ...]:
    names = [name.strip() for name in value.split(",")]
    if any(not name for name in names):
        raise AgentsError(f"--agents needs a comma-separated list of {', '.join(AGENTS)}: '{value}'")
    unknown = sorted(set(names) - set(AGENTS))
    if unknown:
        raise AgentsError(f"--agents: unknown agent {', '.join(unknown)}; choose from {', '.join(AGENTS)}")
    if len(set(names)) != len(names):
        raise AgentsError(f"--agents names an agent twice: '{value}'")
    return canonical(names)


def effective_agents(flag: Optional[tuple[str, ...]], saved: Optional[tuple[str, ...]]) -> tuple[tuple[str, ...], str]:
    """Return the agents to use and where the choice came from: the flag, the saved state, or the default of both."""
    if flag is not None:
        return flag, TEMPORARY
    if saved is not None:
        return saved, SAVED
    return AGENTS, DEFAULT
