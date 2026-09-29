---
name: codex-review
description: Ask OpenAI Codex for an independent read-only review of code changes, a plan, a design, or any other current work, then verify and triage its findings. Use when the user explicitly wants Codex involved — "review it with codex", "ask codex", "let codex check it", "second opinion from codex" — or runs /codex-review; do not use it for an ordinary review that Claude should do alone, or for a conversation with the Codex in the other pane (that is peer-chat). Codex runs headless in a read-only sandbox and nobody talks to it; Claude sends the brief, gets the answer, and re-checks and prioritizes (P1–P4) every finding before anything is done.
argument-hint: "[--astra] [focus text]"
---

# Codex review

Codex reviews the current work read-only. Claude sends it the full context, then checks every finding
on its own before deciding anything. Codex is a second opinion, not an authority.

## Arguments

`$ARGUMENTS`:

- `--astra` — use `gpt-6-astra`. Default is `gpt-5.6-sol`. Effort is always `high`.
- Any other text — an extra focus for the review, or a custom answer format. A custom format
  replaces the "Answer format" section of the brief.

Claude's own model does not change.

## Helper script

All mechanics go through one script. Never run `codex` by hand for this.

The script sits next to this file: set `S` to `scripts/codex-review.mjs` resolved against the folder
this `SKILL.md` was loaded from (the skill's base directory), not against your working directory.

```bash
S="<folder of this SKILL.md>/scripts/codex-review.mjs"
node "$S" init [--astra]                     # prints {dir, model, brief}
node "$S" send <dir> <round> [--timeout s]   # runs Codex, waits, saves and prints the answer
node "$S" status <dir>                       # round states
```

- **How it runs.** `send` runs `codex exec` headless: a read-only sandbox, no approval prompts, and no
  user config, rules, plugins, app tools or hooks. The user does not see or talk to this Codex. Later
  rounds resume the same Codex thread, so it remembers the earlier rounds.
- **Files.** `init` creates the review folder: `<main repo>/.tmp/codex-reviews/<timestamp>-<id>/` when
  the project has a `.tmp/` folder, else `~/.claude/codex-reviews/<timestamp>-<id>/`. You write
  `round-N.md`; the script adds the round header. The answer is `answer-N.md`.
- **Run `send` with `run_in_background: true`.** A high-effort review can take longer than the Bash
  timeout. Wait for the background task to finish; do not start `send` again for the same round.
- **Exit codes:** `0` done · `1` error → report it; the round is cleared and can run again after the
  cause is fixed · `2` timeout → run `send` again or raise `--timeout` (default 45 minutes).
- A failed run, an empty answer or a run with no Codex thread is an error, never "No findings".
- `send` refuses a round that was started and never finished (the helper was killed). Check that no
  `send` for it is still running, then start a new review with `init`.

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

Run `init`, write the brief, run `send <dir> 1` in the background. Tell the user in one line that
Codex reviews headless, with which model.

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
