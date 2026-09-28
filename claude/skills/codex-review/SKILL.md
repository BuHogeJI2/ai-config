---
name: codex-review
description: Ask OpenAI Codex for an independent read-only review of code changes, a plan, a design, or any other current work, then verify and triage its findings. Use when the user explicitly wants Codex involved — "review it with codex", "ask codex", "let codex check it", "second opinion from codex" — or runs /codex-review; do not use it for an ordinary review that Claude should do alone. In agterm it talks to the Codex the user already runs in the other pane of the split, through peer-chat.py; outside agterm it runs Codex headless. Claude neither accepts nor rejects Codex findings by default — every finding is re-checked and prioritized (P1–P4) before anything is done. Also use it when a "Chat from Codex: [codex-review] answer N ready" prompt arrives.
argument-hint: "[--astra] [--exec] [focus text]"
---

# Codex review

Codex reviews the current work read-only. Claude sends it the full context, then checks every finding
on its own before deciding anything. Codex is a second opinion, not an authority.

## Arguments

`$ARGUMENTS`:

- `--astra` — headless only: use `gpt-6-astra`. Default is `gpt-5.6-sol`. Effort is always `high`.
  In agterm the model is whatever the user started in the other pane.
- `--exec` — force the headless mode even inside agterm. Only when the user asks for it.
- Any other text — an extra focus for the review, or a custom answer format. A custom format
  replaces the "Answer format" section of the brief.

Claude's own model does not change.

## Helper script

All mechanics go through one script. Never drive `agtermctl` or `codex` by hand for this.

The script sits next to this file: set `S` to `scripts/codex-review.mjs` resolved against the folder
this `SKILL.md` was loaded from (the skill's base directory), not against your working directory.

```bash
S="<folder of this SKILL.md>/scripts/codex-review.mjs"
node "$S" init [--astra] [--exec]            # prints {dir, mode, model, brief, why}
node "$S" send <dir> <round> [--timeout s]   # agterm: sends a pointer and returns; exec: waits, prints the reply
node "$S" answer <dir> <round>               # agterm: checks answer-<round>.md, records it, prints it
node "$S" status <dir>                       # round states
```

- **Mode.** `agterm` whenever Claude runs inside agterm: the user already started Codex in the other
  pane of the split. `exec` (headless `codex exec`, hard read-only sandbox) outside agterm, or with
  `--exec`. `init` prints `why` for exec mode; tell the user when it is anything other than "not
  running inside agterm".
- **Files.** `init` creates the review folder. agterm mode always uses
  `$TMPDIR/agterm-peer-reviews/codex-reviews/<timestamp>/`: Codex must write its answer there, and its
  sandbox may not reach the repo. macOS cleans `$TMPDIR`, so these folders are not kept for long.
  Exec mode uses `<main repo>/.tmp/codex-reviews/<timestamp>/` when the project has a `.tmp/` folder,
  else `~/.claude/codex-reviews/<timestamp>/`.
  You write `round-N.md`; the script adds the round header and, in agterm, the reply instructions.
  The answer is `answer-N.md`.
- **Exit codes:** `0` done · `1` error → report it · `2` exec timeout → run `send` again or raise
  `--timeout` · `3` nothing was sent and the user must act (no Codex in the other pane, a dialog is
  open there, no split) → tell the user the exact reason and offer `--exec`. Never switch to `--exec`
  on your own.
- In exec mode run `send` with `run_in_background: true`; a high-effort review can take longer than
  the Bash timeout.

## How it runs in agterm

- `send` types one line into Codex's composer through `peer-chat.py --queue`: an idle Codex starts at
  once, a busy one runs it after its current turn instead of mixing it into unrelated work. The line
  points at `round-N.md`, which carries the whole brief and the reply instructions.
- `send` returns right away. **End your turn.** Do not poll or wait. Codex writes `answer-N.md` and
  replies with a prompt that arrives in this pane: `Chat from Codex: [codex-review] answer N ready:
  <path>`. Then run `answer <dir> N` and triage.
- If `send` says delivery is unknown, tell the user the exact error and ask them to look at the Codex
  pane. Never re-send blind.
- If the user asks about a missing reply, run `status <dir>` and check whether `answer-N.md` exists.
  Report what you can verify; if there is an answer, continue with the `answer` step; if not, ask the
  user to look at the Codex pane. Never re-send a `sent` or unknown round.
- The pane is the user's. Its Codex should be dedicated to this pair; if the user is using it for other
  work, ask before starting a review.
- **Read-only is only an instruction here.** The user's Codex runs with its own sandbox, usually
  workspace-write. The brief tells it to stay read-only, but nothing enforces it. When the repository
  must be protected for sure, suggest `--exec`.

[references/agterm-mechanics.md](references/agterm-mechanics.md) has the details for debugging or
changing the script.

## Step 1 — Build the brief

Copy `brief-template.md` from the folder this `SKILL.md` was loaded from into `<dir>/round-1.md` and
fill every section:

- **Original request** — the user's own words, quoted in full. Never paraphrase.
- **Task context** — point to the plan file if a plan was written, to the design if one was
  presented. If neither exists, write down what was discussed and agreed.
- **What to review** — the concrete place: a `git diff` range, changed files, or the plan file.
  Codex reads the code itself; do not paste large diffs.
- **Claims to verify** — your decisions and the reasons for them. Present them as claims.
- **Open questions** and **Concerns** — be honest, including weak spots you already see.
- Never put secrets, tokens or `.env` contents into the brief.

## Step 2 — Round 1

Run `init`, write the brief, run `send <dir> 1`. Tell the user in one line where Codex runs (the other
pane, or headless with which model).

## Step 3 — Triage

Do not agree with Codex by default. Do not reject it by default either. For every finding and
every challenged decision:

1. Check it yourself in the code — read it, reproduce it, run a test when you can.
2. Give it your own priority. Codex's priority is only its opinion: its P1 may be a P3.
3. Pick a verdict:
   - **accept** — real and worth doing. P1 and P2 are always done if accepted.
   - **reject** — wrong, not applicable, or a worse option. Write down why, with evidence.
   - **backlog** — real but P3/P4 and not worth doing now → file it with `/backlog` later.
   - **drop** — real but not worth anything, even a backlog item.

For P3 and lower, decide on your own whether it is worth doing now, filing to the backlog, or
dropping. They never start a new round.

Also check that an accepted fix is the best fix, not just Codex's first idea.

## Step 4 — More rounds (only for serious disagreement)

Send another round only when there is a disagreement about a P1 or P2:

- you reject a finding that Codex rated P1/P2, or
- you and Codex disagree whether something is P1/P2 or P3 and lower.

Maximum 3 rounds in total (round 1 plus up to 2 follow-ups). Write `<dir>/round-N.md` with only
the disputed items: the finding id, your counter-evidence, and the question. Ask Codex to defend
each one with new evidence or withdraw it, and to challenge your rejections if it thinks you are
wrong. Keep the finding ids. Then `send <dir> N`. Items still disputed after round 3 go to the user
with both arguments.

## Step 5 — Report and wait

Report to the user, short:

| id | Codex | Claude | verdict | why |
|---|---|---|---|---|

Then: what you will do (accepted P1/P2), what goes to the backlog, what is dropped or rejected,
and any unresolved disputes with both sides' arguments. Mention the review folder path.

Then **stop and wait for "go"**. Do not change code or file backlog items before it. The only
exception: the user asked in the same request to implement the results after the review — then
continue with the accepted items and the backlog filing.

Codex stays open in its pane; the user closes it when they want.
