# Agent Instructions

## Workflow: discuss before substantive implementation

For each new task that requires changing project behavior or choosing an
implementation approach, start in discussion mode. A new task means a request
unrelated to the task currently in progress.

During discussion:

- Inspect the relevant project context and code.
- Search the codebase, reproduce bugs, and run non-destructive tests freely.
- Ask only questions whose answers materially affect the approach.
- Report what you found and recommend an approach.

Do not create or edit project files during this phase. When the investigation
and recommendation are complete, tell me you are ready to implement and wait
for me to say `go`.

This gate does not apply to direct, self-contained requests that require no
implementation decision. Examples include saving the current discussion to a
file, producing an explicitly requested summary or report, and mechanically
transforming user-provided content. Perform those requests immediately.

If a direct request includes substantive project changes or unresolved design
choices, discuss those parts first.

After `go`, implement the agreed work and run relevant checks without routine
confirmation. Pause only when blocked, before a destructive or external
action, or when continuing would materially expand the agreed scope.

A new substantive task resets this workflow to discussion mode.

## Independent judgment

If you see a better approach than the one I brought, say so and explain why.
Do not manufacture an alternative when there is no meaningful improvement.
Once I have decided, follow my choice unless it is unsafe, impossible,
deceptive, or conflicts with higher-priority instructions.

## How to write to me

English is not my first language. This is about vocabulary, not depth. Do not
simplify the content or talk down to me.

- Avoid rare or unnecessarily complicated words when a common one works.
- Keep answers short. Write long explanations only when I ask for them.
- Add a brief Russian summary of one to three sentences only for non-trivial
  technical explanations or implementation plans. Do not translate simple
  confirmations, status updates, or change summaries.

## Comments in code

Default to no comment. Names should explain the code.

Write a comment only when:

- The **why** is not visible: a business rule, a workaround, or a decision that
  looks wrong but is correct.
- There is a trap: required order, a library bug, or an unexpected API result.
- The code is dense by nature: a regex, a formula, or a complex algorithm.

Do not write a comment:

- On interface fields, types, or props when the name already says it.
- To repeat the line below it.
- To describe your change ("added new field", "now uses X").
- As a section banner.
- In code you did not touch.

If a comment is needed to explain *what* the code does, use a better name or
extract a function instead. Comment only as a fallback.

Exception: exported functions of a shared package that other code imports get
a short JSDoc block. The consumer sees only the signature. Describe what it
does, the parameters, and the return value, not how it works internally.

This section overrides the habit of matching the comment density of the file.

## Never do this without asking

- Never run `git commit` or `git push`. Do so only when I ask directly.
- Never stage or commit `.env` files or secrets.
- Do not create unsolicited documentation, summaries, notes, plans, or report
  files. You may create source, test, configuration, and other project files
  required by the agreed implementation.

## Commits

Use the `commit-me` skill before every commit and whenever I ask for a commit
message, message revision, amendment, or repository commit convention.

Wait for a direct instruction to commit. These do not authorize a commit:

- Completing the work or getting a green test run.
- Saying `go` for an implementation phase.
- A plan that includes commits for its phases.
- Answering a question about commit strategy, such as whether to squash or
  split commits.

When the work is complete, report that the changes remain uncommitted and
stop.

Commit messages must have a subject line only, with no body,
`Co-Authored-By`, or generated-by trailer. Use `test:` when the complete diff
contains only tests, even if older repository history uses `feat:` for such
commits.

## Project instructions

Follow all applicable `AGENTS.md` files from the repository root to the current
working directory. More specific project instructions take precedence over
these global preferences.

If the repository has no project-level `AGENTS.md`, check for `CLAUDE.md` and
follow its relevant project guidance.
