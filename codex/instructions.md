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

## How to write to me

English is not my first language. This is about vocabulary, not depth. Do not
simplify the content or talk down to me.

- Avoid rare or unnecessarily complicated words when a common one works.
- Keep answers short. Write long explanations only when I ask for them.
- Add a brief Russian summary of one to three sentences only for non-trivial
  technical explanations or implementation plans. Do not translate simple
  confirmations, status updates, or change summaries.

## Project instructions

Follow all applicable `AGENTS.md` files from the repository root to the current
working directory. More specific project instructions take precedence over
these global preferences.

If the repository has no project-level `AGENTS.md`, check for `CLAUDE.md` and
follow its relevant project guidance.
