from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass, field
from urllib.parse import unquote
from pathlib import Path
from typing import Callable

from .agents import AGENTS, canonical, target_agent
from .manifest import Entry
from .paths import Environment

MISSING = "missing"
UNKNOWN = "unknown"
SYNTAX_TIMEOUT_SECONDS = 20

_MCP_MENTION = re.compile(r"""^\[{0,2}\s*["']?mcp_servers\b""")
_MCP_HEADER = re.compile(r"^\[\s*mcp_servers\.([A-Za-z0-9_-]+)(?:\.[A-Za-z0-9_-]+)*\s*\]\s*(?:#.*)?$")
# A link destination: <anything but >>, or text with backslash escapes and one level of balanced parentheses.
_MARKDOWN_LINK = re.compile(r"\]\(\s*(<[^>\n]*>|(?:\\.|[^()\s\\]|\((?:\\.|[^()\s\\])*\))+)")
_URI_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
_NODE_SUFFIXES = (".js", ".mjs", ".cjs")


@dataclass(frozen=True)
class RuntimeProblem:
    level: str
    message: str


@dataclass
class McpInventory:
    """MCP server names found in one agent's configuration.

    `unsure` explains why a name that is not found cannot be reported as missing.
    """

    names: set[str] = field(default_factory=set)
    unsure: str | None = None

    def status(self, name: str) -> str | None:
        if name in self.names:
            return None
        return UNKNOWN if self.unsure else MISSING


def entry_agents(entry: Entry) -> tuple[str, ...]:
    return canonical(target_agent(target) for target in entry.targets)


def check_commands(entry: Entry, which: Callable[[str], str | None] = shutil.which) -> list[RuntimeProblem]:
    return [
        RuntimeProblem("error", f"entry '{entry.id}': required command '{command}' is not on PATH")
        for command in entry.requires.get("commands", ())
        if which(command) is None
    ]


def check_mcp(
    entry: Entry, inventories: dict[str, McpInventory], agents: tuple[str, ...] = AGENTS
) -> list[RuntimeProblem]:
    problems = []
    for agent in entry_agents(entry):
        if agent not in agents:
            continue
        inventory = inventories[agent]
        for name in entry.requires.get("mcp", ()):
            status = inventory.status(name)
            if status == MISSING:
                problems.append(RuntimeProblem("error", f"entry '{entry.id}': {agent} MCP server '{name}' is not configured"))
            elif status == UNKNOWN:
                problems.append(
                    RuntimeProblem(
                        "warning",
                        f"entry '{entry.id}': could not determine whether {agent} MCP server '{name}' is configured "
                        f"({inventory.unsure})",
                    )
                )
    return problems


def codex_mcp_inventory(env: Environment) -> McpInventory:
    """Read `[mcp_servers.<name>]` headers from Codex's config.toml.

    Python 3.9 has no TOML parser, so only plain bare-key headers are understood. Any other mention of
    `mcp_servers` (quoted names, inline tables, a bare `[mcp_servers]` table) makes absent names unknown.
    This proves only that a server is configured, not that it works.
    """
    path = env.codex_home / "config.toml"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return McpInventory()
    except (OSError, UnicodeDecodeError) as error:
        return McpInventory(unsure=f"cannot read {env.shorten(path)}: {error}")
    inventory = McpInventory()
    open_string = None
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if open_string is None and _MCP_MENTION.match(stripped):
            match = _MCP_HEADER.match(stripped)
            if match:
                inventory.names.add(match.group(1))
            else:
                inventory.unsure = f"unsupported mcp_servers syntax at line {number} of {env.shorten(path)}"
        open_string, uncertain = _toml_string_state(line, open_string)
        if uncertain:
            inventory.unsure = f"cannot follow TOML strings at line {number} of {env.shorten(path)}"
    return inventory


def _toml_string_state(line: str, open_string: str | None) -> tuple[str | None, bool]:
    """Return the multi-line string still open after `line`, and whether the line could not be followed.

    Knows comments, basic and literal strings, their multi-line forms, and backslash escapes in basic
    strings, so text inside strings and comments is never read as a table header.
    """
    index, length = 0, len(line)
    while index < length:
        if open_string is not None:
            if open_string == '"""' and line[index] == "\\":
                index += 2
            elif line.startswith(open_string, index):
                index += 3
                extra = 0
                while index < length and line[index] == open_string[0] and extra < 2:
                    index, extra = index + 1, extra + 1
                open_string = None
            else:
                index += 1
            continue
        char = line[index]
        if char == "#":
            break
        if line.startswith('"""', index) or line.startswith("'''", index):
            open_string = line[index : index + 3]
            index += 3
        elif char == '"':
            index += 1
            while index < length and line[index] != '"':
                index += 2 if line[index] == "\\" else 1
            if index >= length:
                return None, True
            index += 1
        elif char == "'":
            end = line.find("'", index + 1)
            if end < 0:
                return None, True
            index = end + 1
        else:
            index += 1
    return open_string, False


def claude_mcp_inventory(env: Environment) -> McpInventory:
    """Read the user-scope `mcpServers` keys from ~/.claude.json, without looking at their values."""
    path = env.home / ".claude.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return McpInventory()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return McpInventory(unsure=f"cannot read {env.shorten(path)}: {error}")
    servers = data.get("mcpServers", {}) if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return McpInventory(unsure=f"unexpected mcpServers format in {env.shorten(path)}")
    return McpInventory(names=set(servers))


def check_skill_files(skill: Path, label: str) -> list[RuntimeProblem]:
    """Check scripts (executable bit and syntax) and relative links in SKILL.md, without writing anything."""
    problems = []

    def walk_error(error: OSError) -> None:
        problems.append(RuntimeProblem("error", f"{label}: cannot read {error.filename}: {error.strerror or error}"))

    for current, dirs, files in os.walk(skill, onerror=walk_error):
        dirs.sort()
        for name in sorted(files):
            path = Path(current) / name
            relative = f"{label}/{path.relative_to(skill).as_posix()}"
            try:
                if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
                    continue
                problems += _check_script(path, relative)
            except OSError as error:
                problems.append(RuntimeProblem("error", f"{relative}: cannot read: {error.strerror or error}"))
    skill_md = skill / "SKILL.md"
    try:
        if skill_md.is_file():
            problems += _check_skill_links(skill, skill_md, f"{label}/SKILL.md")
    except OSError as error:
        problems.append(RuntimeProblem("error", f"{label}/SKILL.md: cannot read: {error.strerror or error}"))
    return problems


def _check_script(path: Path, relative: str) -> list[RuntimeProblem]:
    with path.open("rb") as handle:
        first_line = handle.readline(200)
    has_shebang = first_line.startswith(b"#!")
    problems = []
    if has_shebang and not path.stat().st_mode & stat.S_IXUSR:
        problems.append(
            RuntimeProblem("warning", f"{relative}: has a shebang but is not executable; it works only through its interpreter")
        )
    interpreter = first_line.decode("utf-8", errors="replace") if has_shebang else ""
    if path.suffix == ".py" or (has_shebang and "python" in interpreter):
        problems += _python_syntax(path, relative)
    elif path.suffix in _NODE_SUFFIXES or (has_shebang and "node" in interpreter):
        problems += _external_syntax(["node", "--check", str(path)], relative)
    elif path.suffix in (".sh", ".bash") or (has_shebang and re.search(r"\b(ba)?sh\b", interpreter)):
        problems += _external_syntax(["bash", "--noprofile", "--norc", "-n", str(path)], relative)
    return problems


def _python_syntax(path: Path, relative: str) -> list[RuntimeProblem]:
    try:
        compile(path.read_bytes(), str(path), "exec")
    except (SyntaxError, ValueError) as error:
        return [RuntimeProblem("error", f"{relative}: Python syntax error: {error}")]
    return []


def _external_syntax(command: list[str], relative: str) -> list[RuntimeProblem]:
    if shutil.which(command[0]) is None:
        return [RuntimeProblem("warning", f"{relative}: syntax not checked, '{command[0]}' is not on PATH")]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=SYNTAX_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
            env=_syntax_check_environment(),
        )
    except subprocess.TimeoutExpired:
        return [RuntimeProblem("warning", f"{relative}: syntax check timed out")]
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        return [RuntimeProblem("error", f"{relative}: syntax error: {detail[0] if detail else 'exit ' + str(result.returncode)}")]
    return []


def _syntax_check_environment() -> dict[str, str]:
    """Only PATH and a fixed locale, so startup hooks such as NODE_OPTIONS or BASH_ENV never run code."""
    return {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C"}


def _check_skill_links(skill: Path, skill_md: Path, relative: str) -> list[RuntimeProblem]:
    problems = []
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    for number, line in enumerate(text.splitlines(), start=1):
        for link in _MARKDOWN_LINK.findall(line):
            if link.startswith("<") and link.endswith(">"):
                link = link[1:-1]
            link = re.sub(r"\\(.)", r"\1", link)
            if _URI_SCHEME.match(link):
                continue
            target = unquote(link.split("#", 1)[0].split("?", 1)[0])
            if not target or os.path.isabs(target) or target.startswith("~"):
                continue
            if not (skill / target).exists():
                problems.append(RuntimeProblem("error", f"{relative}:{number}: linked file does not exist: {target}"))
    return problems
