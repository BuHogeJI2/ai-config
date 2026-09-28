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
