---
name: jira-ticket
description: >-
  Draft the title and description of a Jira ticket that the user will create themselves: a scoped title, a plain-language description for managers, and acceptance criteria. Use when the user asks to write, draft or reword Jira ticket text — "jira-ticket", "write a ticket for this", "draft a Jira description", "make a ticket out of this bug". Not for a mere mention of Jira, a quoted instruction, a GitHub issue, a PR description or a commit message. It never connects to Jira.
---

# Jira ticket

Write the text of a Jira ticket for the user to paste. The usual readers are managers: they need to see
what the ticket is about, why it matters and when it is done, not how the code works.

## The topic

- With a topic after the invocation, draft that.
- Without one, draft the task currently discussed. If there is no usable topic, ask one short question.
- Build it from the conversation and the user's words. Read code or reproduce only when needed to
  understand the current behavior, and only with non-mutating checks. Code shows what happens now, not
  what the product should do.
- If the requested outcome, the affected behavior or the success condition is missing or
  contradictory, ask one focused question before writing a paste-ready ticket.

## Title

`<Scope> - <short title>`, for example `Acme - Export fails for large reports` or
`Acme/Portal - Let users reset their password`.

- Take the scope from the current request, then from the conversation, then from a ticket scope
  declared in the project's own instructions. Keep it exactly as given, spelling and order included.
- Never derive the scope from a folder or repository name or a Jira issue key prefix. When the scope is
  unknown, write the title without it and say so in one line after the ticket.
- The title says what the ticket is about in a few words: the problem or the change, not the fix's
  mechanics.

## Description

Plain language, a few short paragraphs or bullets.

- **Bug:** what goes wrong, in which situation, who is affected and what it costs them. Add short steps
  to reproduce only when they are known and useful; they can be written for anyone, not only
  developers.
- **Improvement or feature:** what changes, why, and the benefit.
- **Maintenance or refactoring:** the benefit (risk, speed, cost of later work) and what must stay the
  same. Do not invent user-facing functionality.

Avoid technical detail where the ticket makes sense without it. A detail that is needed to understand
the ticket goes here in plain words. An exact product or API term the behavior depends on, such as a
field name, may stay, with a plain explanation. No code links or file paths, and no internal
implementation names unless they are needed or the user asks.

## Acceptance criteria

A list of observable outcomes that show the ticket is done.

- **Feature:** what must work in the new flow, from the user's point of view. Not only the steps to use
  it.
- **Bug:** the correct behavior in the reported situation. No guessed root cause, no promise to fix
  unrelated things.
- **Maintenance:** concrete completion conditions and the behavior that must not change.

Do not add Given/When/Then, a test checklist, performance targets, an estimate, priority, assignee or
release unless the user gave or agreed them.

## Technical notes

Optional, at the end, only for supporting detail the developer needs and the sections above should not
carry. Keep it short. Leave the section out otherwise.

## Format

Jira editors differ: Jira Cloud accepts pasted Markdown, Server and Data Center fields use wiki markup or
plain text. Write text that reads well in all of them:

- The title on its own line, separate from the body, so each can be copied into its own field.
- Section names as plain lines (`Description`, `Acceptance criteria`, `Technical notes`), without `#`
  or `h2.`.
- `- ` for bullets and `1. ` for steps; no bold, italics, inline code or tables.
- Write in Markdown or wiki markup only when the user asks for it.

A fenced block in the reply is only a copy container; its fences are not part of the ticket.

Example shape:

```text
Acme - Export fails for large reports
```

```text
Description
Users who export a report with more than a few thousand rows get an error and no file. Finance runs
these exports every month end and currently has to split them by hand.

Steps to reproduce
1. Open a report with about 10,000 rows.
2. Click Export.

Acceptance criteria
- A report of 10,000 rows exports to a complete file.
- Smaller exports work as before.
```

## Facts

Do not invent details: environments, frequency, numbers, names or decisions nobody stated. Do not
repeat the same fact in several sections. Smaller open questions go after the ticket, outside the text
to paste.

If the work holds independent outcomes that would be accepted separately, still draft the requested
ticket when it is coherent, and suggest the split after it. A frontend and a backend part of one outcome
are not a reason to split.

## Language

The ticket is in English, also in Russian mode, unless the user asks for the ticket text in another
language. No Russian summary inside the text to paste.

## No side effects

Invoking `jira-ticket` only drafts text in the reply. It does not create files or Jira issues, does not
authorize implementation and is not a `go`. Work that was already authorized continues as before.
