---
name: commit-me
description: >-
  Governs every git commit. Load it BEFORE running `git commit` — always, with no exception for cases where committing seems obviously wanted, including "commit this", "fix X and commit it", "push that up", or finishing a task that feels ready to land. It enforces two things: never commit unless the user actually asked, and build the message from this repository's own recent history instead of a generic convention. Also use it when the user asks what a commit message should say, asks you to reword or amend one, or asks you to set up commit conventions for a repo.
---

# commit-me

## Never commit unless asked

This is the rule the skill exists for.

Finishing a task is not a request to commit. Neither is a green test run, a completed refactor, a tidy stopping point, or the user going quiet after you finish. Deciding when work becomes a commit depends on their branch strategy, their review process, and what else they intend to fold in — context you don't have and can't infer from the diff.

**Counts as asking:** "commit", "commit this", "fix X and commit it". An explicit instruction to commit, in some form.

**"Push it" and "land it" are not a request to commit.** They cover commits that already exist. If there are uncommitted changes, ask whether to commit them first; do not create a commit on your own to have something to push.

**Does not count:** "fix the bug", "make the tests pass", "clean this up", "that looks good", "go with phase 3". These are requests to change code. The change is the deliverable; the commit is a separate decision that stays with the user.

Two near-misses worth naming, because both feel like permission and are not:

- **A plan that specifies commits.** Phased plans usually end each phase with a suggested commit message, and approving the plan feels like approving its commits. It isn't. A plan fixes the intended commit *boundaries and wording* — the message to use once the moment comes, not permission for the moment to arrive. "Go with phase 3" authorizes phase 3's work.
- **An answer about commit strategy.** If you ask how something should eventually be landed — squashed or split, red or held back, which branch — the reply settles *how*, not *when*. Never let a question about strategy double as the go-ahead; when you need both, ask for both.

When it's genuinely ambiguous, ask. One short question is cheaper than a commit they have to undo — and undoing is worse than it sounds once it's pushed, or once it's sitting under later work.

Commit only what was asked for. If the working tree carries unrelated changes, stage the relevant paths rather than everything, and say plainly what you left unstaged.

## Build the message from this repo's history

Commit conventions are per-repository and per-author. Don't apply a remembered convention — including one from another repo in the same session.

**A written convention outranks the history.** If the project's instructions state one — `CLAUDE.md`, `.claude/CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md` — follow it, and use the history only for what it leaves unsaid. History records what was done, which can lag what the author now wants: a repo whose last thirty commits type test additions as `feat:` may already have decided on `test:`. Where the two disagree, the written rule is the current intent and the history is the old habit.

With nothing written down, read the actual history:

```bash
git log --author="$(git config user.email)" --no-merges -30 --format='%s'
```

Read it for:

- **Prefix.** Is there a ticket or issue ID, and what shape? Where does it come from — usually the current branch name.
- **Type vocabulary.** `feat` / `fix` / `chore` / `refactor`, or something else, or none.
- **Capitalization and tense** after the type.
- **How domain terms are spelled.** This is the detail most often missed: the same person may write `lead_form` in one repo and `lead form` in another. Match the repo you are in, not the repo you were in ten minutes ago.
- **How multiple changes are joined** when one commit covers more than one thing.
- **Typical length**, so your subject sits alongside its neighbours rather than towering over them.

Weight the recent commits. Older history often shows a style that has since been abandoned, and imitating it reintroduces something the user deliberately moved away from — the last 20–30 commits are the live convention.

For the ticket ID: take it from the current branch name when it carries one. When the branch doesn't — committing directly on `develop` or `main`, say — take it from recent commits belonging to the same piece of work. If that's still unclear, ask. A wrong ticket ID is worse than a delayed commit, because it silently attaches your work to someone else's issue.

## Subject line only

Write the subject and nothing else. Use a single `-m`:

```bash
git commit -m "PROJ-123 fix: keep modal focus inside nested dialogs"
```

**No body. No trailers.** Specifically: no `Co-Authored-By:` line, no "Generated with" attribution, no bullet summary of the diff, no explanation of why. This overrides the usual habit of appending a co-authorship trailer — in this user's repos that trailer is the only thing that has ever put a body on a commit, and they've asked for it gone.

The reasoning behind a change, the alternatives considered, the follow-up work — that belongs in the conversation, the ticket, or a plan document. In a history where every commit is one line, a body isn't extra helpfulness; it's the one entry that breaks the shape of every log view, and it puts information where nobody on the team looks for it.

If a change genuinely can't be described in one subject line, that's usually a sign it should be more than one commit. Say so rather than reaching for a body.

## When there's no history to copy

If the repository has no commits, or none by this author, or the existing messages are too inconsistent to imitate — don't guess.

Propose a message, state the convention you're proposing and why it fits the project, and let the user decide before anything is committed. A first commit sets the pattern every later commit copies, and it's the cheapest moment to get it right.
