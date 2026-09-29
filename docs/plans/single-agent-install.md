# Plan: Install for one agent only

## Task

`scripts/ai-config` installs every target of every manifest entry. A machine that has only Codex
(the second device right now) or only Claude still gets the other agent's files: on an empty home the
plan has 6 Codex creates and 7 Claude creates, and `fileops.py` creates missing parent folders, so a
Codex-only machine gets `~/.claude/skills/*`, `~/.claude/CLAUDE.md` and `~/.claude/rules/shared.md`.
`doctor` also scans local skills and checks requirements for both agents. There is no way to say
"this machine uses only Codex".

## Non-goals

- **Auto-detecting installed agents** (by `~/.claude`, `$CODEX_HOME`, or a command on `PATH`). A fresh
  agent may not have created its home yet, and app-bundled binaries are often not on `PATH`.
- **Trimming skill dependencies.** Selecting Codex does not make every Codex skill work without
  Claude: `claude-review` runs Claude, and `peer-chat` needs `peer-chat.py` and a Claude pane. The README
  states this limit instead.
- **A per-machine skill allowlist** (install only some skills). Selection works per agent only.
- **Changing `restore`, `uninstall` or `adopt` behavior.** They stay independent of the selection.

## Decisions & rationale

- **Explicit selection, saved per machine; no saved selection means both agents.** Existing machines
  keep today's behavior with no migration. Rejected: auto-detection (see Non-goals); refusing the first
  install until an agent is chosen (breaks existing machines and the plain `install` in every doc).
- **Flag `--agents codex|claude|codex,claude`.** Each value is the complete set. Rejected: a repeatable
  `--agent` (a partial value reads like "add"), and a separate `ai-config agents` command (one more
  command for a value set once per machine).
- **Saved in `state.json` as an optional `agents` field; state version stays 1.** The value is a
  non-empty JSON array of strings in canonical order: `["codex"]`, `["claude"]` or
  `["codex", "claude"]`. A missing field means both, like the optional `generated` field today
  (`state.py`). A non-list, non-string, empty, unknown, duplicate or non-canonical value is a state
  error. Reuses the private atomic write and the lock. Rejected: a separate config file (a second file
  to validate, lock and document).
- **`install --agents X` saves X only on a real install, under the lock, after the plan has no
  conflicts, and before any action runs.** A failed install is retried with the same selection. A
  dry run, an invalid flag, or a plan with conflicts never saves.
- **`doctor --agents X` and `diff --agents X` are temporary overrides.** They let the user check a new
  choice before saving it: `doctor --agents codex`, then `install --dry-run --agents codex`. Every
  command that uses a selection prints it and whether it is saved, default, or temporary.
- **The agent of a manifest target comes from its text, before `env.expand()`:** `~/.claude/...` is
  Claude, `~/.agents/...` and `~/.codex/...` are Codex. `CODEX_HOME` can point anywhere (`paths.py`),
  so an expanded path cannot tell. The existing `runtime_checks.entry_agents` already does this per
  entry; it becomes the one helper, per target.
- **The manifest stays complete.** No manifest field for agents; filtering happens when a plan or check
  is built.
- **Disabling an agent is cleanup through `--prune` only.** For an unselected agent, `install` makes no
  creates, relinks, regenerations or legacy `~/.codex/skills` cleanup. The disabled targets are found
  from the full manifest before filtering: their managed links into this repository and their unedited
  generated files become orphans with the reason "agent disabled: <agent>", and `install --prune`
  removes them with a backup, as it does for orphans today. Edited, foreign or ordinary content stays
  untouched. State records are kept until the file is really removed. Targets whose entry was removed
  from the manifest keep today's orphan discovery and ownership rules. Moved-checkout protection
  (`is_recorded_old_link`) keeps working, and a disabled link is never relinked.
- **`--replace-local ID` for an entry with no selected target is an error**, not a silent no-op. `diff`
  of such an entry says it is inactive and suggests `--agents` as a temporary override.
- **`doctor` validates the whole repository and checks the machine for selected agents only.**
  - Whole repository, full manifest: manifest, owner/target rules, skill metadata, privacy
    (`_check_entries`, `_check_repo_skills`, `_check_repo_content`). Filtering the manifest first gives
    false "shared targets" errors in `_check_entries`. These findings may name either agent.
  - Machine, selected agents only: `discover()` itself reads only the selected homes, plugins and
    `SKILL.md` files; runtime checks (`requires.commands`, MCP, skill files) and MCP inventories cover
    entries with a selected target, and `check_mcp` only their selected agents; the install plan uses
    the selection.
  - A disabled agent with an empty home produces no machine findings. Retained managed content of a
    disabled agent still gets accurate state warnings (edited, pending, other checkout), and
    `_check_state` no longer says "install relinks it" for a disabled agent's link; it points to
    `install --prune`.
- **`restore <id>` and `uninstall` ignore the selection and keep it.** `restore` drops the ownership
  record of what it restores (`restore._forget`), so a restored ordinary file, folder, or generated
  file's bytes stay unmanaged and `--prune` never removes them. Only a restored link into this
  repository can be a prune candidate again. This is documented.

## Assumptions

- The helpers live in a new module `scripts/ai_config/agents.py` (`AGENTS`, `target_agent`,
  `parse_agents`, `effective_agents`). `adopt.AGENTS` and `runtime_checks.entry_agents` reuse it.
- Output format of the selection line: `agents         codex (saved)`, in the column layout of the
  plan lines.
- Library functions take the selection as an argument that defaults to both agents, so phases 2 and 3
  land as dormant code and phase 4 turns it on.

## Phases

### Phase 1 — Agent selection model

- **Goal:** the selection can be parsed, stored and read; nothing uses it yet.
- **Changes:**
  - New `scripts/ai_config/agents.py`: `AGENTS = ("codex", "claude")`; `target_agent(target: str)` for
    a raw manifest target; `parse_agents("codex,claude")` with errors for empty, unknown and duplicate
    values; `effective_agents(flag, state)` returning the set and its source (`temporary`, `saved`,
    `default`).
  - `runtime_checks.entry_agents` and `adopt.AGENTS` use the new module.
  - `state.py`: optional `agents` field on `State`; `to_json` writes it only when set; `load_state`
    validates it as decided above.
  - Tests: new `tests/test_agents.py`; `tests/test_state.py` for round trip, missing field = both, and
    each malformed value.
- **Verification:** `python3 -m unittest discover -s tests -t .`
- **Done when:** all tests pass; no command's output changes.
- **Commit:** `feat: add agent selection to state`

### Phase 2 — Planner support (dormant)

- **Goal:** `build_plan` can plan for a subset of agents; the CLI still plans for both.
- **Changes:**
  - `planner.build_plan(..., agents=AGENTS)`: skip targets of unselected agents; legacy Codex copies
    only when Codex is selected; `_find_orphans` turns disabled targets (from the full manifest) into
    "agent disabled" orphans when they hold a managed link into this repository or an unedited
    generated file. Keep the effective-location claims, so cleanup never removes a location an enabled
    target needs (aliased homes).
  - Tests in `tests/test_planner.py` and `tests/test_installer.py`: Codex-only and Claude-only plans on
    empty homes; shared targets; both → one with and without prune, including an edited generated file
    that must stay; one → both; `CODEX_HOME` aliased or outside home; moved-checkout links of a disabled
    agent are cleanup candidates and are never relinked; old records with a changed `CODEX_HOME`.
- **Verification:** `python3 -m unittest discover -s tests -t .`
- **Done when:** tests pass; `scripts/ai-config install --dry-run` output is unchanged.
- **Commit:** `feat: plan install for a subset of agents`

### Phase 3 — doctor support (dormant)

- **Goal:** `run_doctor` can check a subset of agents; the CLI still checks both.
- **Changes:**
  - `skills.discover(env, agents=AGENTS)`: read only the selected homes, plugins and `SKILL.md` files.
  - `doctor.run_doctor(repo_root, env, agents=AGENTS)`: pass the selection to `discover`,
    `_check_install_plan`, `_check_runtime`, `_check_duplicates`, `_check_local_skills`,
    `_check_state`; read MCP inventories only for selected agents; keep `_check_entries`,
    `_check_repo_skills`, `_check_repo_content` on the full manifest. `_check_state` gives the
    `--prune` hint instead of "install relinks it" for a disabled agent's link.
  - `runtime_checks.check_mcp(entry, inventories, agents)`: only selected agents of the entry.
  - Tests in `tests/test_doctor.py`, `tests/test_runtime_checks.py`, `tests/test_skills.py`: a
    Codex-only fake home is clean; the Claude discovery and MCP readers are never called when Claude is
    off; a Claude-only `requires` entry is not checked when Claude is off; a shared MCP requirement
    checks only the selected agent; shared-target validation still passes; retained old-root, pending
    and edited records of a disabled agent get accurate messages.
- **Verification:** `python3 -m unittest discover -s tests -t .`
- **Done when:** tests pass; `scripts/ai-config doctor` output is unchanged.
- **Commit:** `feat: check a subset of agents in doctor`

### Phase 4 — Turn on `--agents`

- **Goal:** a Codex-only machine can install, check and diff for Codex only, and the choice is
  remembered.
- **Changes:**
  - `cli.py`: `--agents` on `install`, `doctor` and `diff`; the selection line; pass the effective
    selection to `build_plan` and `run_doctor`; save it as decided above; reject `--replace-local` for
    an inactive entry; `_diff` shows only selected targets and says an inactive entry is inactive with
    the `--agents` hint.
  - `installer.py` / `state.py`: save the selection with the state before applying actions.
  - `DESIGN.md`: State, Management tool, Installation behavior.
  - Tests in `tests/test_cli.py`, `tests/test_restore.py`: fresh Codex-only and Claude-only installs;
    old state without the field = both; dry run, an invalid flag and a conflicting plan do not save; a
    failed apply keeps the selection for the retry; `--replace-local` of an inactive entry fails;
    `diff` of an inactive entry; `restore` and `uninstall` keep the selection; a restored ordinary
    file or folder is not pruned, a restored repository link is a prune candidate.
- **Verification:**
  - `python3 -m unittest discover -s tests -t .`
  - Fake home, with every command through one function so none touches the real home:

    ```sh
    T="$(mktemp -d)"
    ac() { HOME="$T" CODEX_HOME="$T/.codex" XDG_STATE_HOME="$T/.state" PYTHONDONTWRITEBYTECODE=1 scripts/ai-config "$@"; }
    ac install --agents codex
    test ! -e "$T/.claude" && ls "$T/.agents/skills" "$T/.codex/AGENTS.md"
    ac install            # prints "codex (saved)" and "Nothing to change."
    ac doctor             # 0 errors, no ~/.claude lines
    rm -rf -- "$T"
    ```
- **Done when:** tests pass and the fake-home run gives the results in the comments.
- **Commit:** `feat: install for selected agents only`

### Phase 5 — README

- **Goal:** a reader can set up a one-agent machine from the README alone.
- **Changes:** `README.md`:
  - "Install on a new machine": the one-agent commands (`install --dry-run --agents codex`, then
    `install --agents codex`) before the plain example; the choice is saved.
  - "Update another machine": plain `install` uses the saved choice.
  - Switching: add an agent with `--agents codex,claude`; remove one with `--agents codex --prune`,
    previewed with the same flags and `--dry-run`.
  - Requirements: selection is not dependency trimming (`claude-review`, `peer-chat`).
  - Backups and restore: `restore` can put back a disabled agent's file; only a restored repository
    link is removed again by `--prune`, a restored copy stays.
- **Verification:** read-through; every new command runs through `ac` in the phase 4 fake home.
- **Done when:** the README covers install, update, switching, and the restore note.
- **Commit:** `docs: document installing for one agent`

## Phase dependencies

| Phase | Depends on | Blocks | Parallel with | Nature of the dependency |
|-------|-----------|--------|---------------|--------------------------|
| 1 | — | 2, 3 | — | Phases 2 and 3 use `target_agent` and the agent constants. |
| 2 | 1 | 3, 4 | — | doctor's `_check_install_plan` calls `build_plan` with the new `agents` argument. |
| 3 | 2 | 4 | — | The CLI passes the selection into `run_doctor`. |
| 4 | 1, 2, 3 | 5 | — | Turns on what phases 1–3 built; before it, no command changes behavior. |
| 5 | 4 | — | — | Documents the finished commands. |

## After the plan

On the Codex-only device, where the first install already made Claude files:

```sh
git pull
scripts/ai-config install --dry-run --agents codex --prune
scripts/ai-config install --agents codex --prune
scripts/ai-config doctor
```
