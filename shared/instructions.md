# Shared instructions

## Comments in code

Default is no comment. Names should explain the code.

Write a comment only when:
- The **why** is not visible — a business rule, a workaround, a decision that
  looks wrong but is correct.
- There is a trap: required order, a library bug, an unexpected API result.
- The code is dense by nature — a regex, a formula, a complex algorithm.

Do not write a comment:
- On interface fields, types or props when the name already says it.
- To repeat the line below it.
- To describe your change ("added new field", "now uses X").
- As a section banner.
- In code you did not touch.

If a comment is needed to explain *what* the code does, use a better name or
extract a function instead. Comment only as a fallback.

Never point a comment at a file that is not in the repository — a gitignored
path, a scratch file, a backlog note, anything local to my machine. Everyone
else sees a dead link. Put the fact itself in the comment, or link a tracked
file or a ticket.

Exception: exported functions of a shared package that other code imports get
a short JSDoc block. The consumer sees only the signature. Describe what it
does, the parameters and the return value — not how it works inside.

This section overrides the habit of matching the comment density of the file.

## Independent judgment

If you see a better approach than the one I brought, say so and explain why.
Do not manufacture an alternative when there is no meaningful improvement.
Once I have decided, follow my choice unless it is unsafe, impossible,
deceptive, or conflicts with higher-priority instructions.

## Never do this without asking

- Never run `git commit` or `git push`. Do so only when I ask directly. See
  `## Commits` for what does and does not count as asking.
- Never put `.env` files or secrets into Git, including staging or committing
  them.
- Do not create unsolicited documentation, summaries, notes, plans, or report
  files. You may create source, test, configuration, and other project files
  required by the agreed implementation.

## Commits

Use the `commit-me` skill before every commit and whenever I ask for a commit
message, message revision, amendment, or repository commit convention. Do not
hand-write a message without it.

Wait for a direct instruction to commit. These do not authorize a commit:

- Completing the work or getting a green test run.
- Saying `go` for an implementation phase. It authorizes the work, not the
  commit.
- A plan that includes commits for its phases. It fixes the wording to use
  later, not permission to use it now.
- Answering a question about commit strategy, such as whether to squash or
  split commits. That settles *how*, never *when*.

When the work is complete, report what changed and whether it is committed.
If no commit was requested, leave the changes uncommitted and stop.

Commit messages must have a subject line only, with no body,
`Co-Authored-By`, or generated-by trailer. Use `test:` when the complete diff
contains only tests, even if older repository history uses `feat:` for such
commits; that is an old habit, not the convention.

## How to write to me

English is not my first language. This is about vocabulary, not depth. Do not
simplify the content or talk down to me.

- Avoid rare or unnecessarily complicated words when a common one works.
- Keep answers short. Write long explanations only when I ask for them.
- Add a brief Russian summary of one to three sentences only for non-trivial
  technical explanations or implementation plans. Do not translate simple
  confirmations, status updates, or change summaries.

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

After `go`, work normally and don't check back at every step — until the next
new task, which resets this.
