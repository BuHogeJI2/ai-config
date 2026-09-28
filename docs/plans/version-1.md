# Plan: ai-config version 1

## Task

Codex and Claude skills and global instructions are kept as separate, hand-edited copies in each agent's home folder on each device. The copies have drifted apart (`backlog` and `commit-me` differ between agents, `AGENTS.md` and `CLAUDE.md` state the same policies in different words), and there is no way to move a change to another device except by copying files.

`DESIGN.md` describes the fix: this repository becomes the source of truth, and a small tool (`scripts/ai-config`) links or generates the files in each agent's home. This plan builds version 1 of that tool and moves the existing skills and instructions into the repository.

The migration must not be a "big bang". Each skill and each instruction section moves in its own step and its own commit, is tested in the real agents before the next one starts, and can be rolled back alone. This works because `manifest.json` is an allowlist: `install` touches only listed entries, and everything not yet listed stays where it is and is only reported by `doctor`.

## Non-goals

- Settings, hooks, Codex rules, and MCP configuration. `DESIGN.md` defers them past version 1.
- Managing `agterm`. It is installed by the agterm app and stays app-managed.
- Repeatable test tasks for individual skills (`tests/skills/` in `DESIGN.md`). They are useful only after the skills live in the repository; they can be added later.
- Windows support.
- Continuous integration.

## Decisions & rationale

- **Migrate one skill per step, not all at once.** Every step is: adopt, install, test in the agent, commit. A broken skill affects only itself and is rolled back alone. Rejected: migrating all skills in one run, because a problem found later cannot be tied to one change, and rollback would undo working skills too.
- **`agterm` is external.** Its `SKILL.md` says it is installed by the app (Help ▸ Install Agent Skill…) or a plugin. A repository copy would go stale on every agterm update, and a reinstall from the app would write through the link into the repository. The manifest gets an `external` list so `doctor` knows these names and does not report them as unmanaged. Rejected: managing it in `shared/skills/`, which `DESIGN.md` originally suggested.
- **Build the tool before touching the real agent homes.** Until phase 8, the tool runs on the real machine only in read-only mode (`doctor`, `install --dry-run`). Every writing command is tested first against a temporary fake home. The first real change needs backup, restore, and prune already working, because they are the rollback path.
- **A throwaway probe skill goes first.** Phase 8 checks with a skill nobody depends on that both agents discover linked skills, that Codex uses `~/.agents/skills`, that Claude loads `~/.claude/rules/*.md`, and that the full install → prune → restore cycle leaves no trace. Only then do real skills move.
- **Low-risk skills first; the ones in daily use last.** Skills without scripts go first. `codex-review`, `commit-me`, and `backlog` go last: they are used constantly, and the last two differ between agents and need a merge decision.
- **Instructions move in two stages.** First a baseline that changes nothing: the current files move into the repository as they are, and `shared/instructions.md` is empty. Then one policy at a time moves into `shared/instructions.md`, with one commit each. Rejected: writing the shared file in one go, because a changed wording that affects agent behavior would be hard to find.
- **Python 3.9 standard library, JSON manifest.** Decided when `DESIGN.md` was reviewed: the system Python is 3.9.6, has no TOML reader, and no packages should be installed on each device.
- **Edits through a link reach the repository in both agents.** Checked in phase 8 on 2026-09-28: Claude's and Codex's own edit tools changed the repository file and kept the link. Codex needs the repository folder to be writable in its sandbox; the details are in `DESIGN.md` (Discovery check).
- **Skill owners settled during migration.** `styles-handling` was obsolete and deleted. `commit-me` is shared: the Claude text is newer and stricter, and the Codex folded description fixes invalid YAML. `backlog` stays two agent-specific skills to keep the migration small; merging them is a backlog item. `peer-chat` is two skills because each describes one side of the chat.
- **`peer-chat.py` stays outside the repository.** It is a pinned, unmodified agterm cookbook script tied to the agterm version. The repository records its upstream commit and hash and a manual install recipe instead of copying or downloading it. Rejected: vendoring it, which needs its own install and update design, and downloading it automatically, which would make the tool fetch and run code from the network.
- **The repository is public.** It holds no personal information or secrets; see `DESIGN.md` (Security).
- **Commit a migrated skill only after it passed the test in the agent.** Before the commit, rollback is `git checkout`/`git clean` of the skill folder plus `install --prune` and `restore`. After the commit, it is `git revert` plus the same two commands.

## Assumptions

- Tool code lives in a package, `scripts/ai_config/`. `scripts/ai-config` is a short executable entry point that imports it. A single file without a `.py` extension would be hard to import in tests.
- Tests use `unittest` and run with `python3 -m unittest discover -s tests -t .` from the repository root. `tests/__init__.py` adds `scripts/` to the import path.
- `SKILL.md` frontmatter is read by a small parser for top-level `key: value` lines between the `---` markers. There is no YAML library in the standard library. A block value such as `description: >-` is read as its marker, which is enough because `doctor` only checks that `name` and `description` are present.
- The duplicate-name check also scans plugin skills (`~/.claude/plugins/**/skills/*/SKILL.md`, excluding `.trash`, and `~/.codex/plugins/cache/**/skills/*/SKILL.md`). A plugin name collision is a warning, not an error, because plugin skills are shown with a plugin prefix.
- `adopt` gets a `--to shared|codex|claude` option, which `DESIGN.md` does not have yet. Without it, a skill adopted from one agent cannot be placed in `shared/`.
- Commit types follow the user's rules: `docs:` for documentation only, `feat:` for tool code with its tests, `test:` for test-only changes, `feat: migrate <name> skill` for a migration step.

## Phases

### Phase 1 — Correct DESIGN.md

- **Goal:** the design matches the decisions made while planning.
- **Changes:** `DESIGN.md`:
  - Manifest: add the `external` list with `agterm`; `doctor` reports external names as app-managed and warns if one of them is a link into this repository.
  - Replace the `agterm` migration note: it is external, not a `shared/` candidate.
  - `adopt`: add `--to shared|codex|claude`.
  - Installation: for Codex targets, the planner also checks the legacy `~/.codex/skills/<name>`. If it is identical to the repository source, it is backed up and removed; if it differs, it is a conflict.
  - Compose: on the first install, an existing file that equals the generated output without the marker is backed up and replaced, not reported as a conflict.
  - Skills: a skill refers to its own files by paths relative to the skill folder. A shared skill must not name `~/.claude/skills/...` or `~/.codex/skills/...` for its own files.
  - Migration: add the one-skill-per-step procedure and the rollback recipe from phase 10.
- **Verification:** read the diff; every item above is present, and nothing else changed.
- **Done when:** `DESIGN.md` and this plan do not contradict each other.
- **Commit:** `docs: record external skills and step-by-step migration in design`

### Phase 2 — Tool skeleton and read-only doctor

- **Goal:** `scripts/ai-config doctor` describes the real machine without changing anything.
- **Changes:**
  - `.gitignore` (`__pycache__/`, `.DS_Store`).
  - `manifest.json`: `{"version": 1, "external": ["agterm"], "entries": []}`.
  - `scripts/ai-config`, `scripts/ai_config/` (CLI, path resolution from `HOME`, `CODEX_HOME`, `XDG_STATE_HOME`, manifest loading and validation, frontmatter parser, discovery scan).
  - `tests/__init__.py`, a fake-home helper, and tests.
  - `doctor` checks in this phase:
    - manifest syntax and schema;
    - repository skill folders without a manifest entry;
    - duplicate names per agent across all discovery locations, without regard to letter case;
    - unmanaged and external skills;
    - forbidden files and common secret patterns in the repository;
    - `/Users/<name>` or `/home/<name>` paths in repository content.
  - Exit code 0 when there are no errors, 1 otherwise.
- **Verification:**
  - `python3 -m unittest discover -s tests -t .` passes.
  - `scripts/ai-config doctor` on this machine lists `backlog`, `claude-review`, `commit-me`, `task-plan` (in `~/.codex/skills`), `styles-handling` (in `~/.agents/skills`), and `backlog`, `codex-review`, `commit-me`, `plan` (in `~/.claude/skills`) as unmanaged, shows `agterm` as external, and reports no duplicates.
  - `git status` and the agent home folders are unchanged.
- **Done when:** both checks above hold.
- **Commit:** `feat: add read-only doctor command`

### Phase 3 — Install planner, dry run, and diff

- **Goal:** the tool can say exactly what `install` would do, still without writing anything.
- **Changes:** `scripts/ai_config/` planner:
  - the installation cases from `DESIGN.md` for `symlink` entries, except the state-backed relink of a moved checkout (phase 4);
  - the legacy Codex location check from phase 1;
  - stricter paths: targets limited to the shapes listed in `DESIGN.md`, `~/` remainders that are empty, absolute, or contain `..` rejected, targets under `~/.codex/` resolved through `$CODEX_HOME`, and sources refused when their resolved path leaves the repository;
  - directory equality (relative paths, contents, executable bits, `.DS_Store` ignored, nested links by link text);
  - managed orphans: links in the skill folders that point into this repository and have no manifest entry.

  Also `install --dry-run` and `diff <id>`, with tests for every case in a fake home.
- **Verification:**
  - Tests pass.
  - On this machine, `scripts/ai-config install --dry-run` with the empty manifest prints that there is nothing to do.
- **Done when:** every planner case has a test.
- **Commit:** `feat: add install planner with dry run and diff`

### Phase 4 — Install with state, lock, and backups

- **Goal:** `install` applies a plan safely.
- **Changes:**
  - State file (`state.json`) with the repository root and the links created; `doctor` validates it.
  - Moved checkout: a link recorded in the state file whose text still names the recorded source under the recorded old repository root is relinked, even when the old checkout is gone. Changed or foreign links stay conflicts.
  - Lock file.
  - Atomic link creation: a temporary link, a recheck of the target, then a rename.
  - Backups: folder mode `0700`, file mode `0600`, original modes stored in metadata, and the last 5 kept for each target.
  - Removal of the legacy Codex copy after its backup.
  - Any conflict in the plan stops the whole run before the first write.
- **Verification:**
  - Tests in a fake home cover: first install; second install does nothing; replacing an identical local copy creates a backup; a conflict writes nothing; the legacy copy is removed; a moved checkout is relinked with the old checkout deleted, while changed and foreign links are kept.
  - On this machine, `install` with the empty manifest creates only `~/.local/state/ai-config/` with mode `0700` (`ls -ld ~/.local/state/ai-config`).
- **Done when:** tests pass and the real run changed nothing but the state folder.
- **Commit:** `feat: apply install plans with state and backups`

### Phase 5 — Rollback commands

- **Goal:** every change made by `install` can be undone.
- **Changes:** `restore <backup-id>`, `install --prune`, `install --replace-local <id>`, `uninstall`, and the matching tests.
- **Verification:** a fake-home test runs the full cycle for one skill in both agents:
  1. local copies exist;
  2. `install` links the skill;
  3. the manifest entry is removed;
  4. `install --prune` removes the links;
  5. `restore` puts the backups back;
  6. the home folder tree is byte-for-byte equal to step 1.
- **Done when:** that test passes.
- **Commit:** `feat: add restore, prune, and uninstall`

### Phase 6 — Adopt

- **Goal:** a local skill can be imported into the repository with one command.
- **Changes:** `adopt --agent <agent> --skill <name> --to <owner> [--replace-repo]`:
  - finds the skill in all of the agent's personal locations (both Codex locations);
  - refuses external names, forbidden files, and secrets;
  - copies it into `<owner>/skills/<name>` with executable bits;
  - adds the manifest entry with targets that follow from the owner (`shared` → both agents).

  The manifest is rewritten with 2-space indentation and the entry order kept. `adopt` never changes the agent homes and never commits.
- **Verification:** tests for each owner, for a refused external name, for a refused secret, and for `--replace-repo`.
- **Done when:** tests pass.
- **Commit:** `feat: add adopt command`

### Phase 7 — Complete doctor checks

- **Goal:** a second device cannot look healthy while a managed skill's runtime is missing.
- **Changes:** `doctor` checks, all read-only:
  - `requires.commands`: each command is found on `PATH`.
  - `requires.mcp`: Codex servers from `[mcp_servers.<name>]` sections in `$CODEX_HOME/config.toml`, and Claude servers from the `mcpServers` keys in `~/.claude.json`. This proves only that a server is configured, not that it works. Python 3.9 has no TOML parser, so detection is limited to plain section headers: quoted or dotted names that the reader does not understand produce "could not determine", never "missing". `DESIGN.md` documents this limit.
  - Scripts inside managed skills: files with a shebang must be executable; syntax is checked with `bash -n` for shell, `node --check` for `.js`/`.mjs`, and `compile(source, path, "exec")` for Python. `py_compile` is not used because it writes `__pycache__`.
  - Files named in `SKILL.md` links that do not exist.
- **Verification:** tests in a fake home, including TOML comments, quoted names, unrelated sections, `CODEX_HOME`, a missing command, a non-executable script, and a syntax error. `git status` and the fake home are unchanged after `doctor`.
- **Done when:** tests pass and the real `doctor` still reports 0 errors.
- **Commit:** `feat: check skill dependencies and scripts in doctor`

### Phase 8 — Probe on the real machine

- **Goal:** prove the whole cycle in the real agents with a skill nobody depends on.
- **Changes (temporary, not committed):**
  - `shared/skills/ai-config-probe/` with a `SKILL.md` and a script that prints a fixed word;
  - `claude/rules/ai-config-probe.md` with one instruction ("when asked for the probe word, answer …");
  - their manifest entries.
- **Verification**, each in a new agent session:
  - Codex lists and runs the probe skill from `~/.agents/skills`.
  - Claude lists and runs it from `~/.claude/skills`.
  - Claude follows the probe rule, which proves that `~/.claude/rules/*.md` is loaded.
  - An edit of the probe `SKILL.md` made by each agent through the link appears in the repository, and the link stays a link.
  - Then remove the entries, run `install --prune`, delete the probe files, and check that `doctor` is clean and the agent homes are as before.
- **Done when:** all checks pass. Record the results in the Skills section of `DESIGN.md` (this closes review finding F10).
- **Commit:** `docs: record skill discovery check results`

If a check fails, stop and revise the design before phase 10.

### Phase 9 — Compose for Codex instructions

- **Goal:** the tool can generate `~/.codex/AGENTS.md`.
- **Changes:**
  - The `compose` method: marker header, source and output hashes in the state file, regenerate when sources change, conflict with diff when the output was edited, and the first-install rule from phase 1.
  - `doctor` reports stale output.
  - Tests in a fake home.
- **Verification:** tests pass. On this machine, `install --dry-run` shows no compose entry yet.
- **Done when:** tests pass.
- **Commit:** `feat: generate composed instruction files`

### Phase 10 — Migrate skills, one per step

- **Goal:** every personal skill lives in the repository and is linked into the agents.
- **Procedure for one skill:**
  1. `scripts/ai-config doctor` is clean apart from unmanaged skills.
  2. Review the skill and decide its owner. Replace references to its own files with paths relative to the skill folder where the skill is shared or where the path would change (`~/.codex/skills/...` → the Codex skill now lives in `~/.agents/skills`).
  3. `scripts/ai-config adopt --agent <agent> --skill <name> --to <owner>`, then make any edits from step 2.
  4. `scripts/ai-config install --dry-run`. Check that it shows only this skill: a backup and a link for each target, and removal of the legacy Codex copy where there is one.
  5. `scripts/ai-config install`.
  6. In a new session of each target agent, use the skill on a small real task.
  7. `scripts/ai-config doctor` is clean for this skill.
  8. Commit: `feat: migrate <name> skill`.
- **Rollback of one skill:** before the commit, `git checkout -- manifest.json` and delete the adopted folder; after the commit, `git revert <commit>`. Then run `scripts/ai-config install --prune` and `scripts/ai-config restore <backup-id>` for each backup from step 5.
- **Order**, one commit each:

  | Step | Skill | Agent now | Owner | Why here |
  |------|-------|-----------|-------|----------|
  | 10.1 | `task-plan` | Codex (`~/.codex/skills`) | codex | No scripts. First test of legacy-location removal. |
  | 10.2 | `plan` | Claude | claude | No scripts. First real Claude skill. |
  | 10.3 | `styles-handling` | Codex (`~/.agents/skills`) | deleted | Obsolete; removed with a backup instead of migrated. |
  | 10.4 | `claude-review` | Codex (`~/.codex/skills`) | codex | Has scripts and a test file; checks that executable bits survive. |
  | 10.5 | `codex-review` | Claude | claude | The review tool in daily use. Do not run it during a review. |
  | 10.6 | `commit-me` | both, different | shared | Used for every commit and differs between agents. |
  | 10.7 | `backlog` | both, different | claude, codex | Differs between agents and names its own files by absolute path. |
  | 10.8 | `peer-chat` | both, one side each | claude, codex | Appeared after planning. Needs `peer-chat.py`, which is not in the repository. |

- **Verification:** the procedure above, for each step.
- **Done when:** `doctor` shows no unmanaged personal skills except external ones and the skills that Codex or Claude install themselves.

### Phase 11 — Migrate instructions, one policy per step

- **Goal:** global instructions live in the repository, and shared policies have one wording.
- **11.1 Baseline, no behavior change:**
  - Copy `~/.claude/CLAUDE.md` to `claude/CLAUDE.md` and `~/.codex/AGENTS.md` to `codex/instructions.md` as they are. Create an empty `shared/instructions.md`.
  - Add three manifest entries:
    - `instructions/claude`: `symlink` to `~/.claude/CLAUDE.md`;
    - `instructions/shared-claude`: `symlink` to `~/.claude/rules/shared.md`;
    - `instructions/codex`: `compose` to `~/.codex/AGENTS.md`.
  - Check both files for machine-specific content and personal information first; the repository is public.
  - Run `install --dry-run`, then `install`. `diff` of the new `AGENTS.md` against its backup shows only the marker.
  - Commit: `feat: move global instructions into repository`.
- **11.2 onward, one policy per step:**
  - Choose one policy that both files state, for example the commit rules.
  - Write one wording in `shared/instructions.md` and delete it from `claude/CLAUDE.md` and `codex/instructions.md`.
  - Run `install`, then check the behavior in a new session of each agent.
  - Commit: `feat: share <policy> instructions`.
  - Repeat until nothing shared is left in the agent files.
- **Rollback:** `git revert` the step, then `install`. For the baseline, also run `install --prune` and `restore`.
- **Verification:** `doctor` is clean. In a new session, each agent can state the moved policy when asked.
- **Done when:** no policy appears in more than one instruction file.

### Phase 12 — README

- **Goal:** someone who was not in this conversation can install, update, add a skill, resolve a conflict, restore a backup, and uninstall.
- **Changes:** `README.md`, written for anyone who wants to reuse the public skills. It lists the prerequisites (Python 3.9+, `node`, and for `peer-chat` the agterm app and `peer-chat.py` with its pinned install recipe).
- **Verification:** follow the README in a fake home (`HOME=$(mktemp -d)`) from a fresh clone.
- **Done when:** every command in the README works as written.
- **Commit:** `docs: add README`

### Phase 13 — Second device

- **Goal:** the configuration works on another device, which is the reason this repository exists.
- **Changes:** none planned. Differences found here become fixes in the tool or design.
- **Verification:**
  1. Clone the repository.
  2. Run `doctor`.
  3. Run `install --dry-run`: expect conflicts where local skills differ.
  4. Resolve each conflict with `diff` and `--replace-local` or `adopt --replace-repo`.
  5. Run `install` and test a few skills in both agents.
- **Done when:** `doctor` is clean on both devices.

## Phase dependencies

| Phase | Depends on | Blocks | Parallel with | Nature of the dependency |
|-------|-----------|--------|---------------|--------------------------|
| 1 | — | 2 | — | The tool implements the `external` list, `--to`, and the legacy-location rule defined here. |
| 2 | 1 | 3, 6, 7, 9 | — | Manifest loading, path resolution, and the discovery scan are used by every later command. |
| 3 | 2 | 4 | 6, 7 | `install` executes the plans the planner builds. |
| 4 | 3 | 5, 9 | 6, 7 | Rollback and compose need the state file and backups. |
| 5 | 4 | 8 | 6, 7, 9 | The probe removes itself with `--prune`, and the real migration needs `restore` as its rollback. |
| 6 | 2 | 10 | 3, 4, 5, 7, 9 | Migration steps start with `adopt`. |
| 7 | 2 | 8 | 3, 4, 5, 6, 9 | The probe and every migration step rely on `doctor` to report missing runtimes. |
| 8 | 5, 7 | 10, 11 | 9 | The first real change must prove discovery and `~/.claude/rules` loading before real skills and instructions depend on them. |
| 9 | 4 | 11 | 5, 6, 7, 8, 10 | The Codex instructions entry uses the `compose` method. |
| 10 | 6, 8 | 13 | 11 | Needs `adopt` and a proven install cycle. Each step depends only on the previous step being tested. |
| 11 | 8, 9 | 13 | 10 | Needs `compose` and the proven `~/.claude/rules` loading. |
| 12 | 10, 11 | 13 | — | Documents the finished commands and the final layout. |
| 13 | 10, 11, 12 | — | — | Installs the complete configuration from a fresh clone by following the README. |

## Open questions

| Question | What's unclear | Why it matters | Needed by |
|----------|---------------|----------------|-----------|
| Is a second device available? | Not discussed. | Without it, phase 13 cannot run, and multi-device behavior stays untested. | Phase 13 |
