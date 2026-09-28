# Agent Instructions

## New task: discuss before doing

When I bring you something new, don't start implementing. Ask questions,
investigate the code, and come back with what you found and what you'd suggest.

Investigation is part of this, not gated by it — read, grep, run tests,
reproduce the bug freely, without asking.

Close the phase by telling me you're ready to go. I'll say go. After that work
normally and don't check back at every step — until the next new task, which
resets this.

## In that discussion, don't just agree

If you see a better approach than the one I brought, say so and why. Not as an
obligation — if you don't see one, don't manufacture one. Once I've decided,
drop it and do it my way.

## How to write to me

English is not my first language. This is about vocabulary, not about depth —
do not simplify the content or talk down to me.

- Avoid rare or unnecessarily complicated words when a common one works.
- Keep answers short. Write long explanations only when I ask for them.
- Add a short Russian translation when you explain technical details of an
  implementation, or when we are planning work.

## Never do this without asking

- Never run `git commit` or `git push`. Only when I ask you directly. See
  `## Commits` for what does and does not count as asking.
- Never put `.env` files or secrets into git.
- Never create files I did not ask for — no summary, notes, docs or reports.

## Commits

Use the `/commit-me` skill for every commit. Do not hand-write a message
without it.

Wait for a direct "commit". These are **not** the go-ahead:
- Finishing the work, or a green test run.
- "Go with phase 3" — that authorizes the work, not the commit.
- A plan listing a commit per phase. It fixes the wording to use later, not
  permission to use it now.
- My answer to a question about commit strategy (squash or split, land it red
  or hold it). That settles *how*, never *when*.

When you are done, report what changed, say it is uncommitted, and stop.

Message rules:
- Subject line only. No body, no `Co-Authored-By`, no "Generated with" trailer.
- Type `test:` when the diff is tests. Some repos still type these `feat:` —
  that is the old habit in their history, not the convention. Do not copy it.

## Projects

Read `agents.md` in the project root if it exists.
