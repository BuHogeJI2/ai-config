---
name: claude-review
description: Get an independent Anthropic Claude review of code changes, a plan, or a design, then independently verify and triage its findings. Use when the user asks Claude for a review or second opinion, or explicitly invokes $claude-review. Claude runs headless with read-only tools and nobody talks to it. Do not use for ordinary Codex-only review requests, or for a conversation with the Claude in the other pane (that is peer-chat).
---

# Claude review

Claude reviews the current work read-only. Send it the full context, then independently verify every
finding before deciding what to do. Claude is a second opinion, not an authority.

## Invocation options

Interpret text supplied with the skill as follows:

- `--fable` uses Claude Fable. The default is Claude Opus. Effort is always `high`.
- Any other text is an extra review focus or a requested answer format. A requested format replaces the
  template's `Answer format` section.

The Codex model running this skill does not change.

## Helper

Use the helper for everything. Do not run `claude` directly.

The helper sits next to this file: set `S` to `scripts/claude-review.mjs` resolved against the folder
this `SKILL.md` was loaded from, not against your working directory.

```bash
S="<folder of this SKILL.md>/scripts/claude-review.mjs"
node "$S" init [--fable]                        # prints {dir, model, brief}
node "$S" send <dir> <round> [--timeout <sec>]  # runs Claude, waits, saves and prints the answer
node "$S" status <dir>                          # round states
```

- **How it runs.** `send` runs `claude -p` headless with only `Read`, `Glob` and `Grep`. File access is
  limited to the checkout and the review folder, and no settings, hooks, MCP servers or skills are
  loaded. The user does not see or talk to this Claude. Later rounds resume the same session.
- **Guidance.** This Claude cannot load `CLAUDE.md` or rules files by itself. Before each round-1 attempt
  the helper copies them into `<dir>/guidance.md`, and the round-1 message tells Claude to read it first.
  A warning about an unreadable source means the copy is incomplete: tell the user.
- **Files.** `init` creates `<repo>/.tmp/claude-reviews/<timestamp>-<id>/` when the repository already has a
  `.tmp/` directory, else `$CODEX_HOME/claude-reviews/<timestamp>-<id>/` (`~/.codex` by default). Write
  `round-N.md` there; the helper adds the round header. The answer is `answer-N.md`.
- **Sandbox.** Claude needs the network and writes its session under `~/.claude`. If your sandbox blocks
  that, run `send` with escalation. A login or network failure is reported as an error; say so to the user.
- **Long runs.** A high-effort review can take longer than a command's first yield. If `send` returns a
  running-session identifier, poll that same session until it exits. Never launch `send` twice for a round.
- **Exit codes:** `0` done; `1` error, the round is cleared and can run again after the cause is fixed;
  `2` timeout, run `send` again or raise `--timeout` (default 45 minutes).
- An error result, an unfinished run or an empty answer is an error, never `No findings`. An answer that
  starts with `Note: the reviewer was denied ...` may be partial; take that into account.
- `send` refuses a round that was started and never finished (the helper was killed). Check that no `send`
  for it is still running, then start a new review with `init`.

## 1. Build the brief

Copy [references/brief-template.md](references/brief-template.md) to `<dir>/round-1.md` and complete every
section:

- **Original request:** quote every relevant user message verbatim. Never paraphrase it.
- **Task context:** point to an existing plan or design. If neither exists, describe what was discussed and
  agreed.
- **What to review:** Claude has no shell, so it cannot run `git diff` or any other command. Save the diff
  and any command output it needs into the review folder (for example `<dir>/diff-1.patch`) and name
  those files here, with the changed files and the plan or design. Claude reads files itself; do not paste
  a large diff into the brief.
- **Claims to verify:** state the implementation or design decisions and their reasons as claims, not facts.
- **Open questions** and **Concerns:** include genuine uncertainty, weak spots, and known limits.
- **Extra focus:** include invocation text that is not an option, or `none`.
- Never include secrets, tokens, credentials, or `.env` contents.

## 2. Run round 1

Run `init`, write the brief and the evidence files, and run `send <dir> 1`. Tell the user in one line that
Claude reviews headless, with which model.

## 3. Verify and triage

Do not accept or reject Claude's conclusions by default. For every finding and challenged decision:

1. Check it independently in the code or artifact. Reproduce it or run a safe test when practical.
2. Assign your own P1-P4 priority; Claude's priority is evidence to consider, not the verdict.
3. Choose one verdict:
   - **accept:** real and worth addressing. Accepted P1/P2 items are in scope for the next implementation.
   - **reject:** incorrect, inapplicable, or worse than the current approach. Give concrete evidence.
   - **backlog:** real P3/P4 work that is useful but outside the current implementation.
   - **drop:** real but not worth implementing or recording.

Check that Claude's proposed fix is the best fix, rather than accepting its first suggestion.

## 4. Use follow-up rounds only for serious disagreement

Send another round only when Codex and Claude disagree about a P1/P2 finding or about whether an item is
P1/P2 versus P3/P4. Do not continue rounds for lower-priority details.

Use at most three rounds total. For each follow-up, write `<dir>/round-N.md` containing only the disputed
finding IDs, Codex's counter-evidence, and a focused question. Ask Claude to defend each finding with new
evidence or withdraw it. Preserve finding IDs across rounds. After round 3, report any remaining dispute
to the user with both arguments.

## 5. Report and respect implementation scope

Report concisely:

| id | Claude | Codex | verdict | evidence |
|---|---|---|---|---|

Then state which accepted P1/P2 items should be implemented, which P3/P4 items should enter the backlog,
which items were rejected or dropped, and the review directory path.

Stop and wait for `go` before changing code or filing backlog items. If the user's original request
explicitly asked to implement the review results too, continue with accepted in-scope work instead.
