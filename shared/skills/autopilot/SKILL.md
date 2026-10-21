---
name: autopilot
description: >-
  Finish the current task end to end without checking in with the user: work through every step, commit the verified work (following the plan's commits when one exists), choose the recommended option for each open question, file out-of-scope findings to the backlog, verify the result, and report the decisions at the end. Use only when the user asks for it — "autopilot", "go on autopilot", "continue without me until it's done", "finish this without asking me", "I'm away, take it to the end", "don't wait for me". Do not use it on your own initiative because a task looks long, or for an ordinary "go".
---

# Autopilot

The user has handed the task over and is not watching. Take it to the end: decide instead of asking,
keep working instead of waiting, and leave one report that tells them what happened and why.

Autopilot changes who decides, not what is safe. Everything below that says "stop" or "never" still
holds while the user is away.

## Activation and authority

Autopilot starts only on the user's own request, in words like the ones in the description. Loading
this skill on your own guess grants nothing; without that request, work in the normal mode.

The request gives you three things:

- **No waiting for `go`.** A task that is not discussed yet is investigated and decided by you, the way
  open questions are decided below. Do not stop to present a recommendation.
- **Decisions.** Implementation and design questions inside the task are yours to settle.
- **Commits.** Commit the run's verified work. When a plan existed before autopilot started — a file or a
  plan in the conversation — its phases and messages set the commits. Without one, you choose the
  boundaries (see below).

It gives nothing else: no push, pull request, deploy, release, paid service, data deletion or other
destructive or outward-facing action. Permission the user already gave separately for one of those still
holds.

No commits at all when:

- the user said not to commit for this task — that wins over the request;
- the project's instructions forbid commits on the current branch. Use a feature branch only when those
  instructions or the user's request allow that workflow; otherwise leave the work uncommitted and
  report the conflict.

Before the first change, record the starting point:

```bash
git rev-parse --abbrev-ref HEAD
git rev-parse --verify -q HEAD || echo "no commits yet"
git status --porcelain
```

Every change already in `git status` belongs to the user. Never stage, commit, stash, reset, restore or
reformat it. Work on the current branch; create or switch branches only when the plan, the project's
instructions or the user's request say so.

## Execute and commit steps

With a plan, its phases are the steps, in order. Without one, split the work into steps yourself and
keep that sketch in the conversation, not in a file:

- A step is a coherent change in behavior or a refactoring, complete and verifiable on its own. Code,
  its tests and the docs it needs go together.
- A small task is one step. Split larger work only where each part stands on its own.
- Never split by file count or by time, and never commit work in progress.

For each step:

1. Implement it, following the project's instructions and conventions.
2. Run the step's checks: the verification from the plan, if any, and the tests for the code it
   touched. They must pass with no new failures. A failure the task is meant to fix must be fixed,
   plan or not. A failure that already existed at the starting point and lies outside the task is
   reported, not fixed, and does not block an otherwise verified commit. If an essential
   check cannot run and nothing else checks the same thing, the step is not verified: keep the work
   uncommitted and report the limit.

When commits are allowed (see above), also:

3. Review the step's changes as a reviewer would: wrong scope, debug leftovers, missed files, secrets.
   Read the contents of new files too.
4. Commit through the `commit-me` skill, naming the step's paths so that nothing else in the index
   goes in:

   ```bash
   git add -- <new files of this step>
   git commit -m "<message>" -- <every path this step changed>
   ```

   A plain `git commit` takes the whole index, including what the user staged before the run. Never use
   `git add -A`, `git add .` or `git commit -a`, and never name backlog files or paths from the starting
   `git status`. With a plan, use its message for the phase, corrected to the repository's convention
   and to what the diff actually does.
5. Check that `git show --stat HEAD` lists only the step's paths and that the user's staged entries are
   still staged.

`commit-me` asks the user in two places; under autopilot, decide instead:

- **No history or no clear convention.** Follow a written convention if there is one. Otherwise choose a
  plain one that fits the project, use it for the whole run, and report it.
- **Ticket ID.** Never invent one. If the convention requires an ID and neither the branch nor the
  recent commits give it, do not commit: keep the work and report why.

If a path holds both the user's earlier changes and yours, it cannot be committed safely: leave it as it
is, skip the commits that depend on it, and report it. A step that changed nothing has nothing to
commit; never create an empty commit.

Never amend, rebase, squash or reset commits, including your own from this run.

When the plan turns out wrong in a detail — a file moved, an API differs, a phase is easier split in two
— adapt it and keep going. Keep the plan's commit boundaries where they still make sense, and report the
deviation.

## Open questions and out-of-scope findings

When a question comes up that you would normally ask the user:

1. Read the code and the project's instructions first; many questions answer themselves there.
2. Name the real options — usually two or three.
3. Choose the recommended one: it reaches the agreed outcome, fits the existing conventions, is the
   easiest to reverse, and adds the least.
4. Record it in a decision list kept in the session: the question, the options, the choice, why, and
   how to reverse it. Do not write it into the plan, notes or any other file.
5. Continue.

A finding outside the task — a bug elsewhere, a fragile pattern, a missing test — goes to the backlog
through the `backlog` skill, which chooses where and how. Do not fix it. If filing fails, note the
finding for the report and continue.

## Blockers

Stop a step only when one of these is true:

- It needs authority autopilot does not give (see above).
- It changes the agreed scope or acceptance criteria, rather than how they are met.
- No option is safe and supported.
- A demonstrated blocker: the user or a permission rule denied an action, a dependency or credential is
  missing, or attempts keep failing without new evidence.

Do not use a fixed retry count. Keep fixing a failure while each attempt teaches something new; stop
when it does not.

A denial by the user or by a permission rule is an answer. Do not retry the action or reach the same
result another way. Skip what depends on it, finish the work that does not, and report what was blocked
and why.

A sandbox restriction or an ordinary failure is not a denial. Request the permission through the agent's
normal approval flow, or use a permitted alternative that stays inside the task. If the request is not
answered, treat that step as blocked and continue with independent work.

When the whole task is blocked, keep the finished steps committed, leave the rest of the tree as it is,
and go to the report.

## Verify and report

The task is finished when the feature is complete and works — not when the last step is written.

1. Run the checks the project's instructions require, and the full test suite when the project has one
   that runs in this checkout.
2. Exercise the actual behavior where it can be done locally: run the command, call the function, load
   the page.
3. Review the whole change against the starting point, committed and uncommitted together:
   `git diff <start>` for tracked files — a plain `git diff` misses the committed steps — and the
   contents of every untracked file this run created, which `git diff` does not show. With no starting
   commit, review the full contents of the run's commits instead. Compare with the starting
   `git status` so that the user's earlier work is not counted as this run's.
4. Fix what this review finds, within scope, as one more step: verify, review and commit it like the
   others, so no fix is left uncommitted by accident.

Then write the final report. It is the notification: the user reads it when they come back.

- **Result** — one or two sentences: done, partly done, or blocked.
- **Commits** — hash and subject for each, or "none" and why. Name the message convention if you chose
  one.
- **Uncommitted changes** — the paths left in the tree, and why.
- **Decisions** — each significant choice: the question, the choice, why, and how to reverse it.
- **Backlog** — the items filed, or the findings that could not be filed.
- **Checks** — each command with passed, failed or unavailable, and failures that existed before the
  run. An unavailable check is never counted as passed; do not write "everything works" past one.
- **Blocked or skipped** — what was not done and what it needs from the user.

Leave nothing else behind: no report, notes or summary files.

## Continuity

Autopilot lasts while this session runs; it is not a background job and does not survive the session
ending. If the context is summarized, keep the task, the starting point, the remaining steps, the
decision list and the verification state in the summary.

A message from the user during the run takes priority over this skill. Autopilot ends with the final
report; the next task starts in the normal mode.
