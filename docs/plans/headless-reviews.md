# Plan: Headless review skills

## Task

`codex-review` (Claude side, `claude/skills/codex-review`) and `claude-review` (Codex side,
`codex/skills/claude-review`) ask the other agent for a review. Inside agterm they default to a pane
mode: the brief goes to the agent in the other pane through `peer-chat.py`, that agent writes
`answer-N.md` and sends a pointer back as a `Chat from X:` prompt. The user sees the reviewer in its pane
and can talk to it, so a review is almost the same as a `peer-chat` conversation. That mode also costs a
lot of machinery: delivery states (`sending`, `sent`, `unsent`), an `answer` step that checks a file
another agent wrote, reply instructions appended to the brief, a review-request section in both
`peer-chat` skills, and a `references/agterm-mechanics.md` in each skill.

The user wants the two separated: a review skill with no way for the user to interact with the reviewer.
The main agent runs the reviewer in the background, gets its answer, and checks it. `peer-chat` stays the
only way to talk with the other pane. The reference is `ask-codex` from umputun/cc-thingz
(`plugins/thinking-tools/skills/ask-codex/SKILL.md`): `codex exec --sandbox read-only ... < /dev/null`,
run in the background, then present and verify the result.

Both helpers already have this headless path (`exec` mode, used outside agterm or with `--exec`), with
session resume for later rounds. The work is mostly removal, plus hardening the headless path now that it
is the only one.

## Non-goals

- **A general "ask" or investigation mode.** The skills stay review and second-opinion tools: a review of
  code, a plan or a design, and focused questions about them or about disputed findings. The reference's
  automatic "after 4+ failed debugging attempts" trigger is not added. A headless general-question skill
  would be a separate user decision.
- **Renaming the skills.** `codex-review` and `claude-review` keep their names, triggers (minus the
  `Chat from` ones) and arguments `--astra` / `--fable`.
- **Changing the triage.** Verify every finding, own P1-P4, accept / reject / backlog / drop, at most
  three rounds, stop for `go` — unchanged.
- **Changing `peer-chat` itself** beyond removing the review protocol from it. Its send and receive
  mechanics, `--prepare-message` / `--message-file`, and the Codex `prefix_rule` stay.
- **Adding or changing Codex rules or Claude settings on the user's machine.** No allow rule is added
  automatically for running the reviewer.
- **Shortening the timeout.** The 45-minute default stays configurable with `--timeout`; the reference's
  10-15 minutes is not a requirement.

## Decisions & rationale

- **Headless only; remove the pane mode completely.** Decided with the user. The helper keeps `init`,
  `send` (runs the reviewer, waits, saves and prints the answer) and `status`. Removed: `--exec`,
  `insideAgterm`, `sendAgterm` / `prepareAgterm`, `sent` / `unsent`, `answer`, `deliveryOutcome`,
  `answerProblem`, `pointerMessage`, `messageName`, `replyInstructions`, the `PEER_CHAT` constant, the
  `needsUser` exit code, and `references/agterm-mechanics.md`. Rejected: keeping pane mode behind a flag
  (the user asked for no interaction, and the pane path is most of the code and all of its delivery risk).
- **Each phase removes one whole review protocol, on both sides.** The Claude-side `codex-review` pane
  protocol lives in `codex-review` plus two `peer-chat` sections (Codex's "Review requests from Claude"
  and Claude's `[codex-review] answer N ready`). Removing only one side leaves a dead trigger. So phase 1
  removes the `codex-review` protocol everywhere, phase 2 the `claude-review` protocol everywhere.
- **Codex reviewer: hard read-only and no side-effecting integrations.** Round 1:
  `codex exec -C <cwd> -s read-only -c approval_policy="never" --ignore-user-config --ignore-rules
  -c features.apps=false -c features.plugins=false -c features.remote_plugin=false
  -c features.hooks=false -m <model> -c model_reasoning_effort=high --skip-git-repo-check --json
  -o <file> -`. Later rounds: `codex exec resume <thread> -c sandbox_mode="read-only"` with the same
  approval, ignore and feature flags. The four feature overrides were added after phase 0: app-managed
  plugins and account-level app tools, some of them able to change external state, still loaded under
  `--ignore-user-config`. `approval_policy="never"` is new (today it is inherited, so a
  headless run could wait on an approval). `--ignore-user-config` skips `$CODEX_HOME/config.toml` (its
  MCP servers, plugins, `notify`) while auth still works; `--ignore-rules` drops execpolicy rules such as
  the `peer-chat.py` `prefix_rule`, so the reviewer cannot reach the other pane. Codex can still run
  read-only shell commands such as `git diff`. `--ignore-user-config` does not promise to skip the
  project and system config layers or `hooks.json` files; phase 0 checks those with a fixture. Isolation
  is kept even when guidance does not load: missing guidance is supplied in the brief, never by dropping
  the isolation flags. If some integration source cannot be turned off in a verified way, phase 0 stops
  and reports to the user instead of shipping the helper with it.
- **Claude reviewer: only `Read`, `Glob`, `Grep`; no Bash.** Decided with the user. `--permission-mode
  plan` is a permission check, not a filesystem boundary, and Bash subprocesses are outside the file-tool
  path checks, so a list of denied Bash commands is not enough. Flags: `-p --output-format json --model
  <m> --effort high --tools Read,Glob,Grep --restricted --add-dir <review dir> --permission-mode plan
  --permission-prompts none --disable-slash-commands --strict-mcp-config --no-chrome`, plus
  `--session-id` (round 1) or `--resume` (later). `--restricted` ignores user, project and local settings
  files (so their hooks) and confines file tools to the working directories; `--add-dir` adds the review
  folder so Claude can read files the main agent put there. `--disable-slash-commands` turns off skills,
  so the reviewer cannot load `peer-chat`. Rejected: `--safe-mode` (drops `CLAUDE.md` and does not fence
  file tools); keeping Bash (read-only would only be an instruction).
- **The Claude reviewer gets its guidance from `<dir>/guidance.md`.** Phase 0 showed that `--restricted`
  also drops every instruction file: the project `CLAUDE.md`, `~/.claude/CLAUDE.md` and
  `~/.claude/rules/*.md`. It is still the only flag that both stops the user's hooks and fences file tools,
  so it stays, and the guidance goes in as a file. The helper, not the agent, builds it, so the list of
  sources is fixed in code and tested. Contract:
  - Sources, in this order (user before project, as Claude loads them): `~/.claude/CLAUDE.md`, every
    `~/.claude/rules/**/*.md` (recursive, sorted by path), then in the review target's root `CLAUDE.md`,
    `.claude/CLAUDE.md`, `CLAUDE.local.md`, and every `.claude/rules/**/*.md` (recursive, sorted).
  - Each source gets a heading with its scope (user or project) and its path, and its text is copied
    unchanged, frontmatter included. The preamble says that a rule with `paths:` frontmatter applies only
    to files matching those paths, and that a later project source overrides an earlier user one where
    they conflict.
  - A missing source is skipped silently. An unreadable one is listed in the preamble as "could not be
    read", and the helper prints a warning, so a partial copy never looks complete.
  - Not collected, and stated in the preamble as the reviewer's own job or a known limit: `CLAUDE.md`
    files in subdirectories (the reviewer reads the ones in directories it reviews; they are inside its
    working directory), `CLAUDE.md` files above the repository root, and `@path` imports (not expanded).
    The project `AGENTS.md` is in the working directory, where the reviewer can read it.
  - `guidance.md` is written again before every round-1 attempt, so a retry after a failed round 1 sees the
    current files. Later rounds resume the session, which already read it, and do not rewrite it.
  - The round-1 message starts with a line telling the reviewer to read `guidance.md` first.
- **Without Bash, the main agent supplies the evidence.** The Codex-side SKILL.md tells Codex to save
  `git diff` output (and any command output the reviewer needs) into the review folder, for example
  `<dir>/diff-1.patch`, and name it in "What to review". The Claude reviewer reads it with `Read`. The
  Claude-side `codex-review` needs no such step: the Codex reviewer can run `git diff` itself.
- **The Codex `notify` setting relies on the help text.** Phase 0 found no log trace of the user `notify`,
  so it could not show that `--ignore-user-config` skips it. The help says the flag skips `config.toml`,
  where `notify` lives, and the user decided that is enough. The worst case is the notify program running
  after each review turn; it writes nothing to the repository.
- **Failures are never "No findings".** Claude side: a JSON result with `is_error: true`, a `subtype`
  other than `success`, or an empty `result` fails the round (raw output kept in `answer-N.raw.json`). A
  non-empty `permission_denials` does not fail the round, but the helper prints and saves a first line
  `Note: the reviewer was denied N tool calls; the review may be incomplete.` Codex side: a non-zero exit,
  a missing or empty last-message file, or a missing `thread.started` event in round 1 fails the round,
  clears it and leaves it retryable. Timeouts keep exit code `2`. Today `claude-review.mjs:214` accepts
  any non-empty `result` without checking `is_error`.
- **Each Codex attempt gets a fresh output file.** Today `codex-review.mjs` writes the last message to a
  fixed `answer-N.raw.md` and removes it only after success. If a failed attempt wrote it and the retry
  exits 0 without writing a new one, the old answer is saved as the new one (Codex reproduced this with a
  fake CLI). The helper deletes any leftover output before it starts, and uses a per-attempt name
  (`answer-N.<attempt id>.raw.md`).
- **Keep what the headless path already does right:** the review target is the current checkout
  (`git rev-parse --show-toplevel`) while storage is the main checkout (`--git-common-dir`); storage in
  `<main repo>/.tmp/<x>-reviews/` when `.tmp/` exists, else `~/.claude/codex-reviews/` or
  `~/.codex/claude-reviews/`; folder mode `0700`; explicit thread / session ids; ordered rounds with
  `sendRefusal`; a failed round can run again; a fresh Claude session id after a failed round 1
  (`clearFailedExecRound`); the real-path entry-point check and its test. Never pass
  `--no-session-persistence` or `--ephemeral`: resume needs the session.
- **Folder names get a random suffix on both sides.** `codex-review` uses a timestamp only today; two
  reviews in one second would share a folder. Use `<timestamp>-<8 hex>` as `claude-review` does.
- **Old review folders are refused.** Meta `version` goes from 4 to 5. `readMeta` fails any other version
  with `this review was started by an older version of the skill; run init for a new review`.
- **Codex needs outer permission to run `claude -p`.** Claude needs the network and writes its
  transcript under `~/.claude`, which a restricted Codex sandbox blocks. The helper does not escalate; the
  `claude-review` SKILL.md tells Codex to run `send` with escalation when its sandbox needs it, and the
  helper reports a clear error when Claude cannot authenticate or reach the network. No rule is added.
- **Long runs.** Claude runs `send` with `run_in_background: true` (as today in exec mode). Codex polls
  its own running command session until it exits, and never launches `send` twice.
- **Manifest declares the real requirements.** `skill/codex-review` gets `requires.commands:
  ["node", "codex"]`; `skill/claude-review` gets `["node", "claude"]`. `doctor` then reports a missing
  command. Neither entry declares anything today.
- **Brief templates lose the answer-file exception.** The reviewer creates no files at all; the helper
  saves the answer from the CLI output.

## Assumptions

- `codex` and `claude` on `PATH` are the CLIs the helpers run, as today. An app-bundled binary that is not
  on `PATH` is reported by `doctor` and by the helper's `could not run` error.
- The models stay as they are: Codex `gpt-5.6-sol` (`--astra`: `gpt-6-astra`), Claude `opus`
  (`--fable`: `fable`), effort `high`.
- The flags were checked against `codex-cli 0.159.0` and Claude Code `2.1.284` help output on this
  machine. `--permission-prompts` needs Claude Code 2.1.259 or newer.

## Phases

### Phase 0 — Probe the reviewer flags (paid, needs the user's approval)

- **Goal:** answer the two open questions with real runs before any code is written, so phases 1 and 2
  use flags that are known to work.
- **Changes:** none in the repository. Everything runs in a temporary folder under the scratchpad, and
  each probe is a short prompt to the real model (a few cents each).
- **Evidence rule.** A probe passes only on evidence the model cannot produce by guessing or by refusing
  in prose: the event stream (Codex `--json` events; Claude `--output-format stream-json --verbose` in
  the probes only, whose `init` event lists the tools, MCP servers and skills, and whose tool events show
  every call), files on disk, and random tokens the model can only know by loading or reading them.
  Every probe runs twice: in a fresh round 1 and in a resumed round, because resume takes different
  flags.
- **Setup** (all tokens are fresh random strings, written here as `<T1>` … `<T4>`):
  - `probe/repo/`: a git repository with a committed `notes.txt`, an `AGENTS.md` with
    `If asked for the project canary, answer <T1>.` and a `CLAUDE.md` with the same line and `<T2>`.
  - Integration fixtures in `probe/repo/`, each wired to write its own sentinel file into
    `probe/sentinels/` when it runs: a project `.codex/config.toml` with an MCP server, a project
    `.codex/hooks.json` session hook, a project `.mcp.json` with an MCP server, and a
    `.claude/settings.json` `SessionStart` hook. No project `notify`: Codex ignores `notify` in project
    config whatever the flags, so it proves nothing.
  - `probe/review/diff-1.patch`: a sibling of the repository, outside its working directory, containing
    `<T3>`. This is the folder given to `--add-dir`.
  - `probe/outside.txt`, outside both roots, containing `<T4>`.
- **Non-project sources** are inspected read-only, by name, without printing values; real settings are
  never edited for a probe. On the probe machine the Codex user layer was only `config.toml` (no user
  `hooks.json`, `requirements.toml` or system config), and the Claude user settings had hooks.
- **Positive controls first.** A sentinel that stays empty proves nothing unless the same fixture is shown
  to work without the isolation flags. So each agent first runs a baseline round in `probe/repo/`:
  - Codex baseline: the same command without `--ignore-user-config` and `--ignore-rules`, with the probe
    repository trusted through `-c 'projects."<probe repo>".trust_level="trusted"'` (a one-run override,
    not a settings edit), still `-s read-only` and `approval_policy="never"`. Pass: both project sentinels
    are written, and the events show the MCP server's tools.
  - Claude baseline: the same command without `--restricted`, `--strict-mcp-config` and
    `--disable-slash-commands`, with `--output-format stream-json --verbose --include-hook-events`. Pass:
    both project sentinels are written, the `init` event lists the project MCP server and the skills, and
    hook events show the user hooks running. This is the control for the
    user-level hooks, which cannot be seeded with a sentinel without editing real settings.
  - A fixture that does not activate in its baseline is fixed and the baseline repeated. If it still does
    not activate, that source is inconclusive: stop and report.
  - Empty `probe/sentinels/` before every isolated run.
- **Results (run on 2026-09-29):** see "Phase 0 results" below. The first flags failed two checks, and
  the fallbacks decided below were taken; Decisions above now hold the final flags.
- **Probes (Codex, with the phase 1 flags):**
  1. "What is the project canary? Answer from your instructions only; do not read files." Pass: the answer
     has `<T1>` and the events show no file read. Project `AGENTS.md` loads with `--ignore-user-config`,
     which also drops the project `trust_level` entries of the user's config.
  2. "Quote the first sentence of the 'Independent judgment' section of your global instructions." Pass:
     the exact sentence ("If you see a better approach than the one I brought, say so and explain why.")
     with no file read in the events. `~/.codex/AGENTS.md` is generated from `shared/instructions.md` and
     `codex/instructions.md`, so this one quote covers the Codex global instructions.
  3. "This is a sandbox test. Run `touch probe.txt` and report the exact error." Pass: the debug tool
     trace (`RUST_LOG=debug` on stderr; Codex code-mode shell calls do not appear in the `--json` events)
     shows the command ran and failed, `probe.txt` does not exist, and the run ended without waiting for an
     approval.
  4. Pass after all runs: `probe/sentinels/` is still empty, and the events show no MCP or plugin tool.
  5. The user `notify` in `~/.codex/config.toml`: look for an authoritative trace of it in the baseline
     run (the events, or the Codex log with `RUST_LOG` raised for one run). If the baseline shows it and
     the isolated run does not, it is excluded. If no trace can show it either way, record that its
     exclusion rests only on the `--ignore-user-config` help text and ask the user whether that is enough.
  6. Exit status 0, `thread.started` in the round-1 events, and a non-empty last-message file.
- **Probes (Claude, with the phase 2 flags, plus `--output-format stream-json --verbose
  --include-hook-events` for evidence):**
  1. The project canary. Pass: `<T2>`, with no `Read` event. Project `CLAUDE.md` loads.
  2. "Quote the sentence under 'Projects' in your user instructions." Pass: "Read `AGENTS.md` in the
     project root if it exists.", with no `Read` event. That is the agent-specific `~/.claude/CLAUDE.md`
     (from `claude/CLAUDE.md`).
  3. The 'Independent judgment' quote, as in Codex probe 2. Pass: the exact sentence, with no `Read`
     event. That is the shared rules file `~/.claude/rules/shared.md` (from `shared/instructions.md`),
     a separate source from probe 2.
  4. From the `init` event: the tools are exactly `Read`, `Glob`, `Grep`; no MCP servers; no skills or
     slash commands. Then "Run `touch probe.txt` with Bash." Pass: no Bash call in the events and
     `probe.txt` does not exist.
  5. "Read `../review/diff-1.patch` and give the token in it." Pass: a `Read` event on that path and
     `<T3>` in the answer, so `--add-dir` works under `--restricted`.
  6. "Read `../outside.txt` and give the token in it." Pass: the `Read` is refused and `<T4>` is not in
     the answer, so `--restricted` really fences file tools.
  7. Pass after all runs: `probe/sentinels/` is still empty, and there are no hook events at all (neither
     the project `SessionStart` hook nor the user hooks the baseline showed).
  8. Record the JSON of a success result and of a run with a denied call (`is_error`, `subtype`,
     `permission_denials`) for the phase 2 parser and its fake-CLI fixtures.
- **Fallbacks, decided now:**
  - Codex probe 1 or 2 fails → keep the isolation flags. The main agent puts the guidance into the brief:
    the Claude-side SKILL.md says to name the project `AGENTS.md` and the global `~/.codex/AGENTS.md`
    in "Task context" (the read-only sandbox can read both). Repeat the probe with that brief.
  - Codex probe 4 fails (a project MCP server or hook still runs) → find a `-c` override for that source,
    and keep it only if the repeated probe shows its sentinel stays empty while the baseline still writes
    it. If no override works, stop and report to the user.
  - Claude probe 1, 2 or 3 fails → keep `--restricted`. It fences `Read` to the working directory and the
    review folder, so naming the files would not help: the main agent copies every applicable source into
    the review folder (`<dir>/guidance.md`, with one heading per source: the project `CLAUDE.md`,
    `~/.claude/CLAUDE.md`, and each `~/.claude/rules/*.md`), and the brief names it. Repeat probes 1-3
    with that brief; each must pass on its own, so a partial copy cannot look complete.
  - **Pass criteria for a repeated probe under a guidance fallback.** The no-read criterion stays only
    for the normal probes, which test automatic loading. A fallback probe instead passes when the events
    show a read of each provided source (the named files for Codex, `<dir>/guidance.md` for Claude), each
    expected quote or token matches the source it comes from, and every isolation check (tools, sandbox,
    sentinels, hook events) is unchanged.
  - Claude probe 5 fails → stop and report; the evidence folder design of phase 2 depends on it.
  - Claude probe 7 fails → stop and report; a hook that survives `--restricted` has no known switch.
  - Any other failure → stop and report to the user before phase 1 or 2.
- **Verification:** each probe's pass condition above. The commands, events and outputs are saved in
  the scratchpad for the phase reviews.
- **Done when:** both open questions have an answer, and the flags for phases 1 and 2 are final (the plan
  is updated if a fallback was taken).
- **Commit:** none, unless a fallback changes this plan: then `docs: update headless review plan`.

#### Phase 0 results

Evidence is in the scratchpad folder `phase0/` of the session that ran it: commands (`*.cmd`), events
(`*.jsonl`), Codex debug logs (`*.stderr`) and the Claude result JSON shapes (`fixtures/`). Cost: about
$0.41 for 7 Claude runs, and 7 Codex turns (about 335k input tokens, 217k of them cached; 4.5k output).

- **Codex project layer, control.** `-c 'projects."<repo>".trust_level="trusted"'` did not make Codex load
  the project `.codex/` layer. A temporary `CODEX_HOME` whose `config.toml` trusted only the probe
  repository (with `auth.json` and `AGENTS.md` linked, deleted afterwards) did: the project hook and MCP
  server both wrote their sentinels.
- **Codex isolated runs** (real home, and the temporary home that trusts the repository; fresh and
  resumed): the canary and the "Independent judgment" quote came back while the debug tool trace shows
  no command except the `touch` (the `--json` events do not list code-mode shell calls), so project and
  global `AGENTS.md` load under `--ignore-user-config`; the trace shows `touch probe.txt` failing with
  `Operation not permitted`; no project sentinel was written.
- **Codex integrations: fallback taken.** Under `--ignore-user-config --ignore-rules` alone, the MCP
  servers from `config.toml` were gone, but app-managed plugins (enabled outside `config.toml`) and the
  account-level app tools still loaded. Adding `-c features.apps=false -c features.plugins=false
  -c features.remote_plugin=false -c features.hooks=false` removed them all: no MCP tools, and no MCP
  server launch in the debug log, fresh and resumed. The baseline showed several launches.
- **Codex `notify`.** The user `notify` left no trace in either baseline log, so its exclusion rests on
  the `--ignore-user-config` help text only. The user accepted that (see Decisions).
- **Claude baseline** (no `--restricted`, `--strict-mcp-config`, `--disable-slash-commands`): the project
  `SessionStart` hook and MCP server wrote their sentinels; hook events showed the user hooks running;
  the `init` event listed the project MCP server, an account connector, and the installed skills and
  slash commands; `../outside.txt` could be read.
- **Claude isolated run: fallback taken.** Tools were exactly `Read`, `Glob`, `Grep`; no MCP servers, no
  skills, no slash commands, no hook events, no sentinels; `../review/diff-1.patch` was read through
  `--add-dir`; `../outside.txt` was refused ("--restricted confines the file tools to the working
  directory"). But all three guidance checks failed: the reviewer had no project `CLAUDE.md`, no
  `~/.claude/CLAUDE.md` and no rules file.
- **Claude with `guidance.md`** (fresh and resumed): the events show a `Read` of `guidance.md`, and all three
  quotes match their sources (`CLD-…` from the project section, the "Projects" sentence, the "Independent
  judgment" sentence). Every isolation check above is unchanged; the outside read was refused again in a
  resumed round.
- **Claude result JSON.** Keys include `is_error`, `subtype`, `result`, `permission_denials` (entries
  `{tool_name, tool_use_id, tool_input}`), `session_id`, `total_cost_usd`. A refused `Read` outside the
  roots leaves `subtype: "success"` and adds a `permission_denials` entry.

### Phase 1 — Claude-side `codex-review` becomes headless only

- **Goal:** Claude's Codex review always runs `codex exec`, and the `[codex-review]` pane protocol is gone
  from every skill.
- **Changes:**
  - `claude/skills/codex-review/scripts/codex-review.mjs`: remove the pane mode (list in Decisions);
    `init` takes only `--astra`; meta version 5 and the old-version refusal; random folder suffix; add
    `-c approval_policy="never" --ignore-user-config --ignore-rules` and the four `features.*=false`
    overrides to both calls; a fresh per-attempt output file; fail and clear the round on a missing or empty last
    message or a missing `thread.started`; update the header comment and `usage()`.
  - `claude/skills/codex-review/scripts/codex-review.test.mjs`: drop the pane tests (`deliveryOutcome`,
    `answerProblem`, `insideAgterm`, agterm `reviewBase`). Add tests with a fake `codex` on `PATH` (a
    small Node script in a temp folder that records its argv and stdin and prints scripted JSON events):
    round-1 flags, resume flags, stdin reaches the CLI and ends (EOF), thread id saved, answer saved,
    empty answer fails, missing last-message file fails, missing `thread.started` fails, a stale answer
    from a failed attempt is never taken on retry (first attempt writes output and exits 1, the retry
    exits 0 and writes none → the round fails), non-zero exit fails and clears the round, timeout gives
    exit 2, old meta refused, and no `peer-chat.py` launch even with `AGTERM_ENABLED=1` set.
  - `claude/skills/codex-review/SKILL.md`: rewrite "Arguments", "Helper script" and "How it runs" for
    headless only; drop the `Chat from Codex` trigger from the description; say that the reviewer is
    `codex exec` in a read-only sandbox and the user does not talk to it.
  - `claude/skills/codex-review/brief-template.md`: the reviewer creates no files; remove the answer-file
    and peer-chat exception.
  - Delete `claude/skills/codex-review/references/agterm-mechanics.md`.
  - `codex/skills/peer-chat/SKILL.md`: in "Review requests from Claude", remove only the
    `[codex-review] round N` request and its numbered steps (lines 67-76 today), and the
    `[codex-review] round N` trigger in the description. Keep the `[claude-review] answer N ready`
    paragraph (lines 78-79) until phase 2: it still serves the live `claude-review` protocol.
  - `claude/skills/peer-chat/SKILL.md`: in "Review requests from Codex", remove only the
    `[codex-review] answer N ready` paragraph (lines 63-64 today); the `[claude-review]` request above it
    stays until phase 2.
  - `manifest.json`: `skill/codex-review` gets `"requires": {"commands": ["node", "codex"]}`.
- **Verification:**
  - `node --test claude/skills/codex-review/scripts/codex-review.test.mjs` passes.
  - `python3 -m unittest discover -s tests -t .` passes.
  - `scripts/ai-config doctor` shows no new error or warning.
  - `grep -rn "codex-review\] \|agterm-mechanics\|--exec" claude/skills/codex-review codex/skills/peer-chat claude/skills/peer-chat`
    finds nothing about the removed protocol.
  - With the user's approval (paid): one real round on a small diff, then one resumed round.
- **Done when:** the helper has no pane code, the tests above pass, and neither `peer-chat` skill mentions
  the `[codex-review]` protocol.
- **Commit:** `feat: run codex-review headless only`

### Phase 2 — Codex-side `claude-review` becomes headless only

- **Goal:** Codex's Claude review always runs `claude -p` with read-only tools, and the `[claude-review]`
  pane protocol is gone from every skill.
- **Changes:**
  - `codex/skills/claude-review/scripts/claude-review.mjs`: remove the pane mode (list in Decisions);
    `init` takes only `--fable`; meta version 5 and the old-version refusal; the Claude flags from
    Decisions (`--tools Read,Glob,Grep --restricted --add-dir <dir> --disable-slash-commands`, keeping
    the current ones); write `<dir>/guidance.md` before round 1 and start the round-1 message with a line
    to read it first; `parseJsonReply` fails on `is_error`, a non-`success` `subtype` or an empty
    `result`, and returns a denial note for non-empty `permission_denials`; a clear error when Claude is
    not logged in or cannot reach the network; update the header comment and `usage()`.
  - `codex/skills/claude-review/scripts/claude-review.test.mjs`: drop the pane tests. Add fake-`claude`
    tests like phase 1 (round-1 flags including `--tools Read,Glob,Grep` and no `Bash`, resume flags,
    stdin EOF, `is_error` fails, a non-`success` `subtype` fails, denial note saved, empty result fails,
    non-JSON output fails and keeps the raw output, timeout exit 2, fresh session id after a failed
    round 1, old meta refused, no `peer-chat.py` launch under `AGTERM_*`). `guidance.md` tests, with a
    fake home and a temporary repository: user sources come before project ones; a repository with only
    `.claude/rules/security.md` and no `CLAUDE.md` still gets that rule; a nested
    `.claude/rules/area/x.md` and a nested user rule are included; `paths:` frontmatter is kept; a missing
    source is skipped and an unreadable one is listed with a warning; a retried round 1 rewrites it and
    round 2 does not. Fixtures use the JSON shapes recorded in phase 0.
  - `codex/skills/claude-review/SKILL.md`: headless only; the reviewer has no Bash, so save `git diff`
    and any needed command output into the review folder and name the files in "What to review"; run
    `send` with sandbox escalation when needed; poll a running `send`, never launch it twice; drop the
    `Chat from Claude` trigger from the description.
  - `codex/skills/claude-review/references/brief-template.md`: no files created by the reviewer; say it
    has only read tools and that the listed files in the review folder are the diff and command output.
  - Delete `codex/skills/claude-review/references/agterm-mechanics.md`. Check
    `codex/skills/claude-review/agents/openai.yaml` still matches (it has no pane wording today).
  - `claude/skills/peer-chat/SKILL.md`: remove what is left of "Review requests from Codex" (the
    `[claude-review] round N` request and its steps) and the `[claude-review] round N` trigger in the
    description.
  - `codex/skills/peer-chat/SKILL.md`: remove what is left of "Review requests from Claude" (the
    `[claude-review] answer N ready` paragraph kept in phase 1).
  - `manifest.json`: `skill/claude-review` gets `"requires": {"commands": ["node", "claude"]}`.
- **Verification:**
  - `node --test codex/skills/claude-review/scripts/claude-review.test.mjs` passes.
  - `python3 -m unittest discover -s tests -t .` passes.
  - `scripts/ai-config doctor` shows no new error or warning.
  - `grep -rn "claude-review\] \|agterm-mechanics\|--exec" codex/skills/claude-review codex/skills/peer-chat claude/skills/peer-chat`
    finds nothing about the removed protocol.
  - With the user's approval (paid): one real round from Codex on a small diff saved in the review folder,
    then one resumed round, run through the helper itself (phase 0 tested the raw flags, not the helper);
    the answer must follow a rule that exists only in `guidance.md`.
- **Done when:** the helper has no pane code, the tests above pass, and neither `peer-chat` skill mentions
  the `[claude-review]` protocol.
- **Commit:** `feat: run claude-review headless only`

### Phase 3 — Documentation

- **Goal:** README and DESIGN describe headless reviews and their real requirements.
- **Changes:**
  - `README.md` skill table (lines 39-40): "Runs Codex (Claude) in the background for an independent
    review, then checks each finding."
  - `README.md` "Requirements" (lines 88-99): the review skills need Node and the other agent's CLI,
    installed and logged in, but no pane; agterm and `peer-chat.py` are needed only for `peer-chat`;
    remove "the in-pane mode of the two review skills"; update the one-agent note (`claude-review` still
    runs Claude, `codex-review` runs Codex).
  - `DESIGN.md` line 429: the reviews are headless only, resume the same session for later rounds, keep
    review folders in the main checkout's `.tmp/` or the agent home; the Codex reviewer is in a read-only
    sandbox, the Claude reviewer has only read tools; `peer-chat` is the only pane channel.
- **Verification:** `grep -n "in-pane\|pane mode" README.md DESIGN.md` finds nothing about the reviews;
  `scripts/ai-config doctor` is clean.
- **Done when:** no doc describes a pane review.
- **Commit:** `docs: describe headless review skills`

## Phase dependencies

| Phase | Depends on | Blocks | Parallel with | Nature of the dependency |
|-------|-----------|--------|---------------|--------------------------|
| 0 | — | 1, 2 | — | Fixes the reviewer flags both helpers are written with. |
| 1 | 0 | 3 | 2 | Needs the final Codex flags from phase 0. |
| 2 | 0 | 3 | 1 | Needs the final Claude flags and JSON fields from phase 0. Edits the same two `peer-chat` files as phase 1, in different sections; running both at once needs a merge. |
| 3 | 1, 2 | — | — | The README requirements text says both skills are headless and states their `requires`; it is true only after both phases. |
