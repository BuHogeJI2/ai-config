---
name: backlog
description: File and manage a repo-local backlog of issues, defects and improvements that surfaced during other work but are out of scope to fix now. Use it the moment you notice something worth attention later — a bug outside the current task, a fragile pattern, a missing test, a design problem — instead of only mentioning it in prose. Also handles reviewing the backlog (--list), re-checking whether an item is still real (--check), and adding one on request (--add <description>).
---

# Backlog

A backlog item records something worth attention later, at the moment it is noticed, so it is not
lost when the session ends.

The request selects the mode: a flag — `--list`, `--check [slug]`, `--add <description>` — or the same
intent in plain words ("show the backlog", "is X still a problem?", "add this to the backlog"). An
explicit invocation with no operation lists the backlog.
Automatic activation for a finding means filing that finding, not listing as the final answer.

## Where items live

Always resolve the directory with the script, never from the working directory. The script sits next
to this file: set `S` to `scripts/backlog.mjs` resolved against the folder this `SKILL.md` was loaded
from, and run it from inside the repository:

```bash
S="<folder of this SKILL.md>/scripts/backlog.mjs"
node "$S" path
```

It chooses between two locations:

- `<main repo root>/.tmp/backlog`, found through `git rev-parse --git-common-dir`. Shared by both
  agents and every linked worktree, and it survives a worktree being deleted. Never versioned.
- `<current checkout root>/docs/backlog`. Belongs to that checkout and can be versioned.

Reuse the one that already exists, even if it holds only `resolved/` items. If neither exists, use
`.tmp/backlog` when the main repo has a `.tmp/` directory, otherwise `docs/backlog`. If both exist,
the script stops with a conflict: report it and wait for the user to choose. `path`, `list` and
`show` never create the directory.

Never create `.tmp/`, move items between the locations, change ignore rules, or stage or commit
backlog files — those are the user's calls.

Resolved items move to `resolved/` inside the chosen directory. Never delete an item file or
overwrite an archived one. Files in `docs/backlog` may be tracked, but do not count on git to
restore a record that was never committed.

## Filing an item (the main use)

File **without being asked** when, during other work, you find something that is worth fixing but
wrong to fix now. The user authorizes automatic backlog creation and deduplicating amendments as
an explicit exception to discussion-before-editing and no-unsolicited-notes preferences. This
does not authorize fixing the finding, changing other documentation, or bypassing sandbox
permissions. Use existing evidence and only the focused inspection needed to record it; do not
turn capture into a separate investigation.

Write the file, keep working, and mention it in one line at the end of the turn. If filing is
blocked by permissions, a storage conflict, or the repository cannot be identified, keep working
and report the unfiled finding at the end instead:

> Filed to backlog: `<slug>` — <title> (medium)

When the item is not startable, say so in the same line — `(medium, blocked: needs a decision on X)` —
because a blocked item does not appear in the main `--list` table and is otherwise easy to forget.
For an amendment, say `Updated backlog` rather than claiming a new item was created.

**Do file:** a defect outside the current task; a pre-existing failure you had to work around; a
fragile or duplicated pattern with a real consequence; a missing test for a real failure boundary;
a decision that needs a person and blocks nothing today.

**Do not file:** anything inside the scope you were given — fix that, filing it is scope-dodging;
speculative "could be nicer" polish with no failure behind it; a note that only matters until the
end of this session. Do not make unrelated fixes just because they are small.

### Dedupe first — this is mandatory

The same issue resurfaces across sessions. Before writing a new file:

```bash
node "$S" list --json
```

Inspect likely matches with `backlog.mjs show <slug>`, including blocked items. Matching `where:`
paths are a reason to compare the problems, not proof they are the same issue.

If an existing item covers the same problem, **amend it** with a dated
`## Addendum — <what is new> (YYYY-MM-DD)` section, raise `priority` only if new evidence justifies
it, and extend `where:` when there are source locations. Do not add an addendum when there is no
new information. Keep amendments within the line cap by tightening existing wording without
losing evidence.

Check that a new slug is unused in both the active and `resolved/` directories. For a recurrence of
an archived issue, pick a new slug and reference the archived one — never reuse an archived slug,
since resolved `after:` dependencies still point at it.

### Priority rubric

Pick from the failure, not from how interesting the problem is.

- **high** — wrong behaviour reaches users, or it blocks a suite, or it gets more expensive the
  longer it sits.
- **medium** — a real defect, contained, with no deadline.
- **low** — cleanup, ergonomics, cosmetics. Nothing breaks if it is never done.

The `## Reasoning` section defends the label chosen. If it cannot, the label is wrong.

### Item format

Copy `TEMPLATE.md` from the folder this `SKILL.md` was loaded from. Filename is a kebab-case slug of
the title, placed in the directory `backlog.mjs path` prints (not its `resolved/`):
`<backlog dir>/<slug>.md`. Set `created:` to today's date.

```markdown
---
priority: high
created: 2026-09-04
where: [path/to/file.ts, path/to/other.tsx]
related: [other-item-slug]
after: [must-land-first-slug]
blocked: product owner must choose between X and Y
---

# Short name for the problem

## Description
## Reasoning
## Possible fix
```

- `where:` — the source files a fix would touch. Real repo-relative paths, checked to exist. This is
  what makes `--check` mechanical rather than a guess, so fill it even when the fix is uncertain.
  Omit it only when there is no meaningful source location, such as a deferred decision; never
  invent one.
- `related:` — slugs of other items worth reading alongside this one. A **cross-reference only**: it
  carries no ordering. Omit when there is none.
- `after:` — slugs that must be finished first, because doing this one before them would be undone or
  wrong. A dependency, not a theme. It clears itself: a slug stops blocking once that item is
  resolved. Only a resolved item clears it: an unknown slug keeps blocking and `list` warns about it,
  since it is usually a typo. Do not repeat an `after:` slug in `related:`.
- `blocked:` — one line naming what this waits on when it is **not** another backlog item: a person's
  decision, an open PR, an external release. Say who or what unblocks it, not that it is blocked.

`after:` and `blocked:` both keep an item out of the main `--list` table, so use them only for
something genuinely not startable. "Would be easier later" is not blocked.

The helper reads a limited frontmatter format, not full YAML: keep scalar fields on one line and
lists in bracket form (`[path/to/file.ts, other/path.ts]`). Do not use multiline YAML values.

### Keep it short

**Hard cap: 60 lines for the whole file.** Description is the longest section and stays within 2–3
paragraphs. Reasoning is 1–3 sentences. Possible fix is a short list of steps, or one paragraph.

Cite evidence — a file and line, an error message, a command that reproduces it — rather than
describing it at length. A reader who has never seen the session must understand the problem, and
that is served by precision, not by volume.

## `--list` (also the no-argument default)

```bash
node "$S" list
```

Print both tables. Rows are sorted by priority, oldest first inside each priority. The first is
work that can be picked up now; the second, **BLOCKED**, is items
held by `after:` or `blocked:` and shows what each waits on instead of its title. Do not read the item
files — the tables are the answer. Add one line of your own only if something stands out, such as
several high items naming the same file, or a whole priority band sitting in the blocked table.
Use `list --json` when metadata such as `where:` is needed to support that observation.

## `--check [slug]`

Verify whether an item is still real. Someone may have fixed it, or the code it describes may be gone.

1. **Choose the item.** If a slug was given, use it. Otherwise run `list --json` and ask the user
   with a short choice question, using your question tool when you have one. When there are more than 4
   items, ask twice — first the priority band, then the item inside it. If there are no items, report the empty backlog. Never guess which item the user meant.
2. **Read it:** `backlog.mjs show <slug>`.
3. **Verify against the code as it is now.** Read every path in `where:`; with no `where:`, test the
   evidence or decision the body records. Run the command or test the item names, if it names one.
   Check `git log` on those paths since `created:`. The item's claims are a snapshot of a past
   session — treat them as claims to test, not as facts. A missing path or a passing unrelated test
   is not proof of a fix.
4. **Re-check the block, if there is one.** A `blocked:` line is the easiest field to go stale — the
   decision may have been taken, the PR merged. Report whether it still holds. `after:` is handled
   by the helper. If code differs across worktrees or a fix is only uncommitted, disclose that
   before proposing a shared update.
5. **Report one verdict**, with the evidence that produced it:
   - **still actual** — say what you confirmed.
   - **already fixed** — name what fixed it (commit, current source, relevant passing test).
   - **partly fixed** — identify what remains and whether the priority should change.
   - **cannot tell** — say exactly what is missing to decide. Leave the file untouched.

Checking is not permission to implement the fix. Follow the discussion → `go` workflow before
clearing blockers, narrowing items, or archiving them unless those changes were already approved.
For a proven and approved resolution, run `backlog.mjs resolve <slug>`. It archives the item without
overwriting an existing archive and reports items that become startable. Never resolve on plausibility.

When recommending a next step, give a short assessment from the current code — not from the
item's old account:

- **Summary** — what the problem is and why it was deferred, in one or two sentences. Not the title.
- **Effort** — one line: the files, call sites, test coverage or open design choice that set the cost.
- **Blast radius** — one line: affected callers or shared behaviour. Inspect dependents before
  calling a change contained.
- **Materiality** — one line: who is affected now and the cost of leaving it, including items it
  blocks. Say so when there is no user-visible symptom.

## `--add <description>`

The user hands you the problem in their own words. Expand it into the format above: dedupe, read the
code well enough to fill `where:` with real paths when the issue has a source location, choose a
priority against the rubric and defend it.

Adding an item follows the filing workflow without another discussion round. Ask only if the
issue cannot be identified from the request and context. With no description, file the issue
that just came up in the conversation. Adding an item never authorizes implementing its fix.
