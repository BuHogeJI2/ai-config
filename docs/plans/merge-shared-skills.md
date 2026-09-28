# Plan: merge backlog and planning into shared skills

## Task

Two skills exist as separate copies per agent, so every change has to be made twice, and the copies
have already drifted apart:

- `backlog`: `claude/skills/backlog` (entry `skill/backlog`) and `codex/skills/backlog` (entry
  `skill/codex/backlog`). `TEMPLATE.md` and `scripts/backlog.test.mjs` are identical, and
  `scripts/backlog.mjs` behaves the same in both. The Codex copy only renames variables and drops three
  comments. The two `SKILL.md` texts state the same rules in different words. This is the backlog item
  `docs/backlog/merge-backlog-skill-into-shared.md`.
- `plan` (Claude, `claude/skills/plan`) and `task-plan` (Codex, `codex/skills/task-plan`): the same
  planning workflow under two names. Codex's text is a shorter rewrite of Claude's, with four additions.

The goal: one `shared/skills/backlog` and one `shared/skills/planning`, each installed for both agents
from one source. The user chose the new name `planning` for both agents.

## Non-goals

- No change to the `ai-config` tool or its tests. Tests use `plan` and `task-plan` only as fixture
  names.
- No change to the rules the skills enforce, beyond merging the two wordings.
- No merge of `codex-review`/`claude-review` or of the two `peer-chat` sides. Those differ because each
  describes one side of a pair.
- No aliases under the old names `plan` and `task-plan`.
- No automatic deletion of unmanaged old copies on other machines (see Phase 2).
- Historical documents stay as they are: `docs/plans/version-1.md`, the resolved backlog archive, and
  the git history.

## Decisions & rationale

- **Two independent phases, one complete commit per merged skill.** Each phase moves the skill, edits
  the manifest, updates the README and DESIGN references, installs on this machine and is tested.
  - Rejected: a move-only commit followed by a wording commit, because it would leave Claude-only text
    in `shared/` for one commit.
  - Rejected: add-before-remove for `planning`, because `plan`, `task-plan` and `planning` side by side
    would give each agent two skills that compete for the same requests.
- **`backlog` base: the Claude text and the Claude `backlog.mjs`.** The Claude text explains the reasons
  behind each rule, and its script keeps the comments. These parts become neutral:
  - Drop the Claude-only `argument-hint` frontmatter.
  - Replace "`$ARGUMENTS` selects the mode" with neutral mode selection. A flag (`--list`,
    `--check [slug]`, `--add <description>`) or the same intent in plain words selects the mode, and a
    bare explicit invocation with no operation lists. Claude Code appends `ARGUMENTS: <args>` to a skill
    that has no `$ARGUMENTS`, as observed in the session that wrote this plan.
  - Replace `AskUserQuestion` with "ask with a short choice question, using the agent's question UI when
    it has one". Keep the two-step selection (priority band, then item) for long lists, without
    requiring a four-option widget.
  - Change "Shared with Codex" to "shared by both agents".
  - Carry over two Codex details the Claude text lacks: use the current date for `created:`
    (`codex/skills/backlog/SKILL.md:93`), and state that an unknown `after:` slug stays blocking and warns
    (`:99`).
  - Keep automatic filing of findings unchanged (both texts, line 13).
- **`backlog` gets `agents/openai.yaml`** (display name "Backlog", a short description, and a
  `$backlog` default prompt), so Codex shows it clearly, as it does for `commit-me`.
- **The `backlog` entry declares `requires.commands: ["node", "git"]`.** The helper runs under Node and
  calls `git` directly, so `doctor` should report either one missing on a new machine.
- **`planning` base: the Claude `plan` text plus Codex's four additions.** The Claude text explains
  the reasons, which helps a model apply the rules to cases they don't name. The additions, from
  `codex/skills/task-plan/SKILL.md`:
  1. Apply the workflow in every interaction mode; an internal plan, task list or planning-tool state is
     not the plan artifact (line 10).
  2. Unresolved external contracts, security boundaries, migration or cutover strategy, persistence
     semantics and concurrency models count as blocking (line 34).
  3. Name concrete files, symbols, interfaces and tests where the repository supports them (line 88).
  4. Label a valid command that cannot run yet as a post-setup gate, and give a check that runs now
     (line 107).

  Two more from Codex's text:
  - its "private decision ledger" wording;
  - its inspect-first handling of a cold request (line 38). This replaces Claude's "nearly everything is
    blocking" (`claude/skills/plan/SKILL.md:38`), which can produce unnecessary questions.

  Keep the atomic-phase techniques as optional patterns, not a required add/migrate/remove recipe.
  - Rejected: Codex's text as the base, because it drops the reasons.
- **The `planning` description is a folded YAML value (`>-`).** The current `plan` description fails a
  strict YAML parse at `claude/skills/plan/SKILL.md:3` ("gate: if"). Claude was observed loading the skill
  anyway, and `doctor` is not a full YAML parser, so nothing reports this today.
- **`planning` metadata and evals:**
  - `agents/openai.yaml`: display name "Planning", default prompt "Use $planning …".
  - `evals/evals.json` moves along with `skill_name: "planning"`. It keeps its three scenarios and adds
    three: an artifact requested in plan mode, an unresolved external contract, and an unavailable
    command that needs a post-setup gate. This file is a list of scenarios for manual or skill-creator
    runs; no runnable evaluator exists.
- **Tests in fresh paid agent sessions are opt-in.** The repository's `AGENTS.md` requires the user's
  agreement before running them. Static checks cannot prove how either agent passes arguments or
  triggers a skill, so each phase proposes these tests and runs them only after the user says yes.
  "Done when" lists only the static checks. Without the smoke tests, the phase report says that
  discovery and argument handling are unverified.
- **The fake-home test uses the uncommitted working tree.** A phase is tested before its commit, and a
  fresh clone holds only committed snapshots. So the test installs the pre-change commit first, then
  copies the complete working tree (edits, new files and deletions) over the clone:

  ```sh
  S=$(mktemp -d)
  git clone -q . "$S/repo" && git -C "$S/repo" checkout -q <pre-change commit>
  export HOME="$S/home" CODEX_HOME="$S/home/.codex" XDG_STATE_HOME="$S/home/.local/state" PYTHONDONTWRITEBYTECODE=1
  "$S/repo/scripts/ai-config" install
  rsync -a --delete --exclude .git --exclude __pycache__ --exclude .DS_Store <repository path>/ "$S/repo/"
  ```

  The phase checks then run in `"$S/repo"` with the same environment. Remove `$S` afterwards.

## Assumptions

- The switch happens on this machine first. Other machines follow the migration note in Phase 2.
- `ruby` (preinstalled on macOS) is available for the strict YAML check, as it was during the skill
  migration. Without it, the fallback is to confirm by eye that each frontmatter value is folded or has
  no `: ` inside it.

## Phases

### Phase 1 — Merge `backlog` into `shared/skills/backlog`

- **Goal:** one `backlog` skill, installed for both agents from `shared/`.
- **Changes:**
  - `git mv claude/skills/backlog shared/skills/backlog` and `git rm -r codex/skills/backlog`.
  - `shared/skills/backlog/SKILL.md`: the neutral edits listed under Decisions. The description stays
    Claude's (it parses as YAML today); verify it again after editing.
  - New `shared/skills/backlog/agents/openai.yaml`.
  - `manifest.json`: replace `skill/backlog` (claude) and `skill/codex/backlog` with one entry,
    `skill/backlog`, source `shared/skills/backlog`, targets `~/.agents/skills/backlog` and
    `~/.claude/skills/backlog`, `requires: {"commands": ["node", "git"]}`.
  - `README.md`: the skills table row (`backlog` becomes "both"), and the note at line 45 that `backlog`
    has one copy per agent.
  - `DESIGN.md:402`: the migration note now says it was merged.
  - `node shared/skills/backlog/scripts/backlog.mjs resolve merge-backlog-skill-into-shared`.
- **Verification:**
  - `node --test shared/skills/backlog/scripts/backlog.test.mjs` passes (11 tests).
  - `ruby -ryaml -e 'YAML.safe_load(File.read("shared/skills/backlog/SKILL.md").split(/^---$/)[1]); YAML.safe_load(File.read("shared/skills/backlog/agents/openai.yaml")); puts "ok"'`
    prints `ok`.
  - `grep -n -E 'argument-hint|\$ARGUMENTS|AskUserQuestion|Shared with Codex|~/\.claude|~/\.codex' shared/skills/backlog/SKILL.md`
    finds nothing.
  - `python3 -m unittest discover -s tests -t .` passes.
  - Fake-home test (see Decisions for the setup):
    1. `install --dry-run` shows exactly `relink` for the two backlog targets.
    2. `install` relinks them, backs up the old links, and records the entry id `skill/backlog` in the
       state.
    3. A second `install` applies 0 changes.
  - On this machine: `scripts/ai-config doctor` has 0 errors, and `install --dry-run` shows only the
    two backlog relinks. Then `install`.
  - **With the user's agreement:** fresh `claude -p --no-session-persistence` and
    `codex exec --ephemeral` sessions in a throwaway git repo with at least five items in two priority
    bands. Run `--list` and `--check <slug>` both as flags and in plain words, and `--check` without a
    slug to exercise the neutral two-step selection. No files may change.
- **Done when** (static checks):
  - the manifest has one `skill/backlog` entry for `shared/skills/backlog`;
  - both installed `backlog` links point to `shared/skills/backlog`;
  - `doctor` is clean;
  - the backlog item is in `docs/backlog/resolved/`.

  If the user agreed to smoke tests, both agents must also pass them.
- **Rollback:** `git revert --no-commit <phase commit>` restores the old sources in the working tree.
  Then run `install --dry-run` and `install`, which relink to them. A rollback commit is a separate
  commit and needs the user's direct "commit". Restoring the link backups alone would leave broken
  links, because the old source folders are gone until the revert.
- **Commit:** `feat: share backlog skill`. This message is a suggestion; committing still waits for the
  user's direct "commit".

### Phase 2 — Merge `plan` and `task-plan` into `shared/skills/planning`

- **Goal:** one `planning` skill for both agents, replacing `plan` (Claude) and `task-plan` (Codex).
- **Changes:**
  - New `shared/skills/planning/SKILL.md`: `name: planning`, a folded description that combines both
    trigger lists, and the text described under Decisions.
  - New `shared/skills/planning/agents/openai.yaml`, and `shared/skills/planning/evals/evals.json`, moved
    from `claude/skills/plan/evals/` and updated.
  - `git rm -r claude/skills/plan codex/skills/task-plan`.
  - `manifest.json`: remove `skill/plan` and `skill/task-plan`, and add `skill/planning` (source
    `shared/skills/planning`, targets `~/.agents/skills/planning` and `~/.claude/skills/planning`).
  - `README.md`: the skills table (one `planning` row, both agents), the dry-run example at line 161
    (`~/.claude/skills/plan`), the `adopt --skill plan --to claude` example at line 200 (it becomes
    `--skill planning --to shared`, because `--to claude` would add a second, competing target), and "Update another
    machine", which gains `install --prune` for removed or renamed skills.
  - `DESIGN.md:404`: `claude-review` stays the counterpart of `codex-review`, and `planning` is now
    shared.
- **Verification:**
  - The ruby YAML check from Phase 1, on `shared/skills/planning/SKILL.md` and its `openai.yaml`.
  - `python3 -c 'import json; d=json.load(open("shared/skills/planning/evals/evals.json")); assert d["skill_name"]=="planning"; print(len(d["evals"]))'`
    prints `6`.
  - ``git grep -n -E 'task-plan|skills/plan([^a-z-]|$)|`plan`|--skill plan([^a-z-]|$)' -- README.md DESIGN.md manifest.json shared claude codex``
    finds nothing. Before the change it lists all 12 current references, including `README.md:38`,
    `:161` and `:200`.
  - `python3 -m unittest discover -s tests -t .` passes.
  - Fake-home test (see Decisions for the setup):
    1. `install --dry-run --prune` shows exactly `create` for the two `planning` targets and `prune` for
       `~/.claude/skills/plan` and `~/.agents/skills/task-plan`.
    2. `install --prune` backs up both pruned links.
    3. A second `install` applies 0 changes.
    4. Seed an unmanaged `~/.codex/skills/task-plan` and show that it gets no action. This is the
       migration note below.
  - On this machine: `doctor` has 0 errors, and `install --dry-run --prune` shows only those four
    actions. Approve it only if nothing else is listed, since `--prune` acts on every orphan link. Then
    `install --prune`, and restart both agents.
  - **With the user's agreement:** fresh sessions in both agents. Confirm that a plan request triggers
    `planning`, that a cold request gets inspection first and questions only about real blockers, and
    that `plan`/`task-plan` are no longer listed. In a new interactive Codex session, the display name is
    "Planning".
- **Done when** (static checks):
  - the manifest has `skill/planning` and neither `skill/plan` nor `skill/task-plan`;
  - `SKILL.md` has `name: planning`, and `openai.yaml` shows "Planning" and `$planning`;
  - both installed `planning` links point to `shared/skills/planning`, and `~/.claude/skills/plan` and
    `~/.agents/skills/task-plan` are gone;
  - `doctor` is clean;
  - the grep above is empty.

  If the user agreed to smoke tests, both agents must also pass them.
- **Rollback:** `git revert --no-commit <phase commit>`, then `install --dry-run --prune`, then
  `install --prune`. This recreates the `plan` and `task-plan` links and prunes the `planning` links.
  A rollback commit needs the user's direct "commit". As in Phase 1, the link backups alone are not a
  rollback.
- **Migration note for other machines:**
  - After `git pull`, run `install --dry-run --prune`, then `install --prune`.
  - `--prune` removes only links into this repository. It does not look at the legacy Codex folder, so
    a machine that never installed the migrated baseline can still have ordinary `plan` or `task-plan`
    copies in `~/.claude/skills`, `~/.agents/skills` or `~/.codex/skills`. Those copies compete with
    `planning`.
  - Check those three folders by hand and remove old copies deliberately, after a backup. The tool
    reports them in `doctor` as unmanaged skills and never deletes them.
- **Commit:** `feat: merge plan and task-plan into planning skill`. This message is a suggestion;
  committing still waits for the user's direct "commit".

## Phase dependencies

| Phase | Depends on | Blocks | Parallel with | Nature of the dependency |
|-------|-----------|--------|---------------|--------------------------|
| 1 | — | — | 2 | None: separate folders, manifest entries and README rows. Both edit `manifest.json`, `README.md` and `DESIGN.md`, so doing them one after the other avoids merge conflicts. That is a preference, not a dependency. |
| 2 | — | — | 1 | None, as above. |

## Open questions

| Question | What's unclear | Why it matters | Needed by |
|----------|---------------|----------------|-----------|
| Does `planning` trigger as reliably as `plan` and `task-plan` did? | The merged description combines two trigger lists, and only live sessions show how each agent matches it. | A skill that fails to trigger silently stops enforcing the readiness gate. | Phase 2's opt-in smoke tests, if the user agrees to them. If they fail, adjust the description before committing; without them, report triggering as unverified. |
| Is a second machine running an older setup? | Unknown which machines have ordinary `plan` or `task-plan` copies. | Old copies compete with `planning` there. | Phase 13 of `version-1.md` (second device), or the first `git pull` on another machine. |
