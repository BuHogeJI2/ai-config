---
name: claude-review
description: Get an independent Anthropic Claude review of code changes, a plan, or a design, then independently verify and triage its findings. Use when the user asks Claude for a review or second opinion, or explicitly invokes $claude-review. In agterm it talks to the Claude the user already runs in the other pane of the split, through peer-chat.py; outside agterm it runs Claude headless. Also use it when a "Chat from Claude: [claude-review] answer N ready" prompt arrives. Do not use for ordinary Codex-only review requests.
---

# Claude review

Claude reviews the current work read-only. Send it the full context, then independently verify every
finding before deciding what to do. Claude is a second opinion, not an authority.

## Invocation options

Interpret text supplied with the skill as follows:

- `--fable` uses Claude Fable in headless mode. The default is Claude Opus. Effort is always `high`. In
  agterm the model is whatever the user started in the other pane.
- `--exec` forces the headless mode even inside agterm. Use it only when the user asks for it.
- Any other text is an extra review focus or a requested answer format. A requested format replaces the
  template's `Answer format` section.

The Codex model running this skill does not change.

## Helper

Use the helper for the review state and the headless mode. Do not drive `claude` or `agtermctl` directly.

The helper sits next to this file: set `S` to `scripts/claude-review.mjs` resolved against the folder
this `SKILL.md` was loaded from, not against your working directory.

```bash
S="<folder of this SKILL.md>/scripts/claude-review.mjs"
node "$S" init [--fable] [--exec]
node "$S" send <dir> <round> [--timeout <sec>]
node "$S" sent <dir> <round>
node "$S" unsent <dir> <round>
node "$S" answer <dir> <round>
node "$S" status <dir>
```

- **Mode:** `agterm` whenever Codex runs inside agterm: the user already started Claude in the other pane of
  the split. `exec` (headless `claude -p` in plan mode) only outside agterm, or with `--exec`. `init` prints
  `why` for exec mode; if it says anything other than `not running inside agterm`, tell the user.
- **Files:** agterm mode always uses `$TMPDIR/agterm-peer-reviews/claude-reviews/<timestamp-id>/`: both
  agents must write there, and a repo `.tmp/` may be outside your sandbox or outside the folder Claude was
  started in. macOS cleans `$TMPDIR`, so these folders are not kept for long. Exec mode uses
  `<repo>/.tmp/claude-reviews/<timestamp-id>/` when the repository already has a `.tmp/` directory, else
  `~/.codex/claude-reviews/<timestamp-id>/`. Write `round-N.md` there. The helper adds the round
  header and, in agterm, the reply instructions. The answer is `answer-N.md`.
- **Exit codes:** `0` done; `1` error; `2` exec timed out, so run `send` again or raise `--timeout`; `3`
  nothing was sent and the user must act.

## How it runs in agterm

1. `send <dir> <round>` writes the pointer message into a private peer-chat file and prints one command:
   `peer-chat.py --to claude --message-file <name>`.
2. Run that exact command, as printed, with nothing added or changed. It matches a `prefix_rule` in
   `~/.codex/rules/default.rules`; your sandbox blocks the agterm socket, so request escalation if asked.
3. Record the outcome at once. Run `unsent` only on positive evidence that nothing was typed:
   - exit 0, or the error says `delivery was confirmed` → `sent <dir> <round>`, then end your turn. Do not
     poll or wait.
   - `unsent <dir> <round>` only when: the command never started (not found, not executable); or it exited
     1 and its last line is a `peer-chat: ` error without `do not resend`, `submit withheld`,
     `composer cleared` or `composer cleanup` (wrong pane, no split, busy composer); or it exited 130 and
     says `nothing was typed`. Then tell the user the exact reason and offer `--exec`.
   - anything else — one of those markers, a traceback, a signal, no output, a tool interruption →
     delivery is unknown. Leave the round as is, report the exact error and ask the user to look at the
     Claude pane. Never re-send blind.
4. Claude writes `answer-N.md` and replies with a prompt that arrives in this pane:
   `Chat from Claude: [claude-review] answer N ready: <path>`. Run `answer <dir> <round>` and triage.

- If the user asks about a missing reply, run `status <dir>` and check whether `answer-N.md` exists. Report
  what you can verify; if there is an answer, continue with the `answer` step; if not, ask the user to look
  at the Claude pane. Never re-send a `sent` or unknown round.

- If the send refuses because more than one session shares this checkout, this Codex was started without
  its pane's session id. The fix is the launch flag in the `peer-chat` skill; only the user can apply it.
  Never pass `--session` with an id you inferred.
- The Claude pane is the user's. It should be dedicated to this pair; if the user is using it for other work,
  ask before starting a review.
- **Read-only is only an instruction here.** The user's Claude runs with its own permissions. The brief tells
  it to stay read-only, but nothing enforces it. When the repository must be protected for sure, suggest
  `--exec`.

Do not load the `agterm` skill for this workflow. Only when debugging the helper, read
[references/agterm-mechanics.md](references/agterm-mechanics.md).

## Headless (exec) mode

`send` runs Claude with `--permission-mode plan` and returns with the answer. A high-effort review can
exceed a command tool's first yield: if the command returns a running-session identifier, poll that same
session until it exits. Do not launch `send` twice.

## 1. Build the brief

Copy [references/brief-template.md](references/brief-template.md) to `<dir>/round-1.md` and complete every
section:

- **Original request:** quote every relevant user message verbatim. Never paraphrase it.
- **Task context:** point to an existing plan or design. If neither exists, describe what was discussed and
  agreed.
- **What to review:** identify the exact diff range, changed files, plan, or design. Let Claude read code
  itself instead of pasting a large diff.
- **Claims to verify:** state the implementation or design decisions and their reasons as claims, not facts.
- **Open questions** and **Concerns:** include genuine uncertainty, weak spots, and known limits.
- **Extra focus:** include invocation text that is not an option, or `none`.
- Never include secrets, tokens, credentials, or `.env` contents.

## 2. Run round 1

Run `init`, write the brief, and run `send <dir> 1` (plus the peer-chat command in agterm). Tell the user in
one line where Claude runs: the other pane, or headless with which model.

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

Claude stays open in its pane; the user closes it when they want.
