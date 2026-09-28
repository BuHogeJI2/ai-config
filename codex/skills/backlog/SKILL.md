---
name: backlog
description: File and manage a repo-local backlog of concrete issues, defects, and improvements found during other work but outside the current task. Use automatically when such a finding should be captured without interrupting the main workflow. Also use when asked to list the backlog, check whether an item is still relevant, or add an item.
---

# Backlog

Capture out-of-scope findings when noticed so they survive the session without interrupting the
current task. Discuss or fix them later.

Interpret the user's request directly: `$backlog --list`, `$backlog --check [slug]`, or
`$backlog --add <description>`. Explicit invocation without a mode or request defaults to listing.
Automatic activation for a finding means filing that finding, not listing as the final answer.

## Storage and helper

Requires Node.js and Git. The helper sits next to this file: set `S` to `scripts/backlog.mjs`
resolved against the folder this `SKILL.md` was loaded from, not against your working directory.
Run it from inside the repository being discussed:

```bash
S="<folder of this SKILL.md>/scripts/backlog.mjs"
node "$S" path
```

Resolve storage through the helper for every operation. It checks two locations:

- `<main repo root>/.tmp/backlog`, shared with Claude Code and all linked worktrees through
  `git rev-parse --git-common-dir`, including worktrees that may later be deleted.
- `<current checkout root>/docs/backlog`, belonging to that checkout and suitable for versioning.

Reuse whichever backlog directory already exists, including one containing only archived items.
If neither exists, use `.tmp/backlog` when the main repository's `.tmp/` directory exists;
otherwise use `docs/backlog`. If both exist, the helper stops with a conflict: report it and wait
for the user to choose a location. Never create `.tmp/` or move items automatically. Listing,
checking, and resolving the path do not create an empty backlog directory.

Resolved items live in `resolved/` beneath the selected backlog directory. Never discard item
files or overwrite an existing archive. `.tmp/backlog` remains unversioned; files in `docs/backlog`
may be tracked, but do not assume Git can restore an uncommitted record. Do not stage backlog
files or change repository ignore rules automatically.

The commands below use `backlog.mjs` as shorthand for the full helper path above.

## Automatic filing

File **without asking**, then continue the current task. The user authorizes automatic backlog
creation and deduplicating amendments as an explicit exception to discussion-before-editing and
no-unsolicited-notes preferences. This does not authorize fixing the finding, changing other
documentation, or bypassing sandbox permissions. If filing is blocked by permissions, a storage
conflict, or the repository cannot be identified, keep working and report the unfiled finding
at the end.

Use existing evidence and only the focused inspection needed to record it; do not turn capture
into a separate investigation. Mention the result in one line at the end of the turn:

> Filed to backlog: `<slug>` — <title> (medium)

For a blocked item, include the reason: `(medium, blocked: needs a decision on X)`.
For an amendment, say `Updated backlog` rather than claiming a new item was created.

**File:** a concrete out-of-scope defect, a pre-existing failure encountered during the task, a
fragile or duplicated pattern with a real consequence, a missing test for a real failure boundary,
or a decision that can wait.

**Do not file:** work already in the agreed scope, speculative polish without evidence, or a note
that matters only until the session ends. Do not make unrelated fixes just because they are small.

### Dedupe first

Run `backlog.mjs list --json` before creating an item. Inspect likely matches with
`backlog.mjs show <slug>`, including blocked items. Matching `where:` paths are a reason to compare
the problems, not proof they are the same issue.

If an existing item covers the same problem, amend it with a dated
`## Addendum — <what is new> (YYYY-MM-DD)`, extend `where:` when there are source locations, and
raise priority only if new evidence justifies it. Do not add an addendum when there is no new
information. Keep amendments within the line cap by tightening existing wording without losing
evidence.

Check that the proposed slug is unused in both the active and resolved directories. For a
recurrence of an archived issue, choose a new descriptive slug and reference the archived item;
do not overwrite the archive or reopen its slug, which may be used by resolved dependencies.

### Priority and format

- **high** — wrong behavior reaches users, blocks a suite, or grows more costly over time.
- **medium** — a real, contained defect with no deadline.
- **low** — cleanup, ergonomics, or cosmetics; nothing breaks if it is never done.

Use [TEMPLATE.md](TEMPLATE.md). Create `<backlog-directory>/<slug>.md`, where the directory
is the output of `backlog.mjs path`, not its `resolved/` archive subdirectory. A slug uses lowercase
letters and digits separated by single hyphens. Use the current date for `created:`.

- `where:` — repository-relative source paths, checked to exist in the current checkout.
  Omit when the finding has no meaningful source location; do not invent one for a deferred decision.
- `related:` — other slugs worth reading; cross-references, not dependencies. Omit if empty.
- `after:` — slugs that must be completed first. Do not repeat them in `related:`. Only an archived
  item satisfies a dependency; an unknown slug remains blocking and produces a warning.
- `blocked:` — a non-backlog dependency, such as a person's decision, a PR, or an external release.
  Name what or who unblocks it. Omit if empty.

Both `after:` and `blocked:` keep an item out of the startable table. Use them only when work
genuinely cannot start, not when doing it later would merely be easier.

The helper reads a limited frontmatter format, not full YAML: keep scalar fields on one line and
lists in bracket form (`[path/to/file.ts, other/path.ts]`). Do not use multiline YAML values.

**Hard cap: 60 lines per item.** Description: at most 2–3 paragraphs. Reasoning: 1–3 sentences
defending the priority. Possible fix: a short list or paragraph. Include concrete evidence such as
a file and line, an error, or a reproduction command. Do not include credentials or secret values.

## List

Run `backlog.mjs list`. Return its startable table and BLOCKED table when present, plus any warnings.
Items are ordered by priority, oldest first within each priority.
Do not read individual item files for a plain list request. Add a short observation only if useful;
use `list --json` when metadata such as `where:` is needed to support that observation.

## Check

1. If no slug was supplied, run `list --json` and ask the user which item to check using a concise
   question. If there are no items, report the empty backlog. Never guess the selection.
2. Read the item with `backlog.mjs show <slug>`.
3. Verify its claims against the current checkout: inspect every `where:` path, investigate missing
   paths, run relevant safe reproduction commands or tests, and check `git log` since `created:`.
   If `where:` is absent, verify the claim using the evidence or decision recorded in the body.
   A missing path or a passing unrelated test is not proof that the issue is fixed.
4. Recheck `blocked:` against available evidence. `after:` is handled by the helper. If code differs
   across worktrees or a fix is only uncommitted, disclose that before proposing a shared update.
5. Report one verdict with evidence: **still actual**, **already fixed**, **partly fixed**, or
   **cannot tell**. For the last verdict, leave the file untouched.

When recommending a next step, give a brief assessment based on the current checkout:

- **Summary** — what the problem is and why it was deferred, in one or two sentences.
- **Effort** — one line naming the files, call sites, test coverage, or unresolved design choice
  that determines the cost.
- **Blast radius** — one line naming affected callers or shared behavior; inspect dependencies
  before calling a change contained.
- **Materiality** — one line stating who is affected now and the cost of leaving it, including
  any items it blocks. Say when there is no user-visible symptom.

Do not repeat the item's title as its summary or guess costs from the item's old account.

Checking is not permission to implement the fix. Follow the discussion → `go` workflow before
clearing blockers, narrowing items, or archiving them unless those changes were already approved.
For a proven and approved resolution, run `backlog.mjs resolve <slug>`. It archives the item without
overwriting an existing archive and reports items that become startable. Never resolve on plausibility.

## Add

For `--add <description>` or a natural-language capture request, use the filing workflow: dedupe,
verify source paths when present, choose and defend the priority, then write the item without
another discussion round. With no description, capture the issue just discussed. Ask only if the
issue cannot be identified from the request and context. Adding an item never authorizes
implementing its fix.
