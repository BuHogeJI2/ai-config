---
name: planning
description: >-
  Produce a phased, independently committable implementation or refactoring plan for a codebase change, grounded in the discussion that preceded it and in repository evidence. Use this whenever the user asks for a plan, roadmap, migration sequence, ordered steps, or phased approach to changing code — including phrasings like "write up a plan", "how should we approach this refactor", "break this into steps/phases", "plan out the migration", "what's the order of work here" — and also when a design discussion has converged and the natural next artifact is a written plan, even if the user never says the word "plan". Use it as well when revising or extending a plan that already exists, in plan mode or any other mode. The skill enforces a readiness gate: if any real ambiguity remains, it returns to discussion and asks before writing anything.
---

# Planning

## What this is for

A plan is a handoff artifact. The reader might be the user next week, a teammate who wasn't in this conversation, or a fresh session with no memory of it. They should be able to execute it without asking you anything.

That bar is what every rule below serves. When a rule seems inconvenient, check it against that bar and use judgment.

Apply the same workflow in every interaction mode, including an agent's plan mode. An internal plan, a task list, or a planning tool's state is not a substitute for the plan artifact the user reads.

## Scale the ceremony to the change

A phased plan with a dependency table is right for work that spans multiple commits, touches several areas, or carries sequencing risk. For a change that's one file and obviously ordered, that structure is overhead dressed up as rigor.

If the request is small, say so and offer the short version — task, approach, verification — rather than manufacturing five phases. The user asked for a plan because they want clarity, not because they want a document.

## Step 1 — The readiness gate

The plan has to reflect what was actually discussed and decided. Before writing anything, work out whether you know enough.

**First, read the code.** A lot of apparent ambiguity dissolves on contact with the repository — existing conventions, patterns, and constraints answer questions you'd otherwise put to the user. Reading is cheaper than asking and it respects their time. Only what survives this pass is a real question.

**Then build a private decision ledger.** List every decision the plan depends on, and classify each:

- **Decided** — settled in the discussion. Note where, so you can cite it in the plan's rationale.
- **Assumed** — never discussed, but the codebase's own conventions leave one reasonable answer (new tests go beside existing ones; the new module follows the existing directory layout). Record these in the plan so they're visible and correctable.
- **Blocking** — genuinely ambiguous. Two or more defensible answers exist, and the choice changes the code, the phase breakdown, or what "done" means.

**The test for Assumed vs. Blocking:** imagine the user reading the finished plan. Would this choice surprise them? Would a competent engineer with the same context have picked differently? If yes, it's blocking.

Some choices are blocking unless the discussion or a clear repository convention settles them: externally observable contracts, security boundaries, migration or cutover strategy, persistence semantics, and concurrency models. Don't downgrade one of these to an assumption just because an answer is easy to invent — these are the choices that are most expensive to get wrong.

**Any blocking item stops the plan.** Don't write around a hole, and don't fill it with a plausible-sounding choice. An unclear plan announces itself and gets fixed; a confident plan resting on a guess gets executed, and the guess only surfaces once the code is written. That asymmetry is why the gate is strict here.

So when there are blocking items: don't write the plan. Go back to discussion. Ask the questions directly, explain what each one changes about the plan, and offer your recommendation where you have one — you're resolving ambiguity, not administering a quiz. Then plan.

Two failure modes to avoid on either side. Don't manufacture doubt about things the discussion clearly settled or the codebase clearly answers; interrogating the user about decisions they already made is its own way of not listening. And if the skill is invoked cold, with little or no prior discussion, inspect the repository first, then ask about the blockers that survive — don't fill the gaps with plausible guesses.

## Step 2 — Where the plan goes

- **If the user named a location** — a path, a filename, "put it in the repo", "add it to the ticket" — write it there.
- **Otherwise, render it in the conversation.** Don't create files unprompted, and don't open with "where should I save this?" — the chat rendering is the default. Once it's written, a brief offer to save it is fine.

## Step 3 — Write the plan

Assume no shared context with the reader. Use this structure:

```markdown
# Plan: <short title>

## Task
What we're changing and why. Lead with the problem and the motivation,
not the solution — that's what lets a reader judge whether a phase still
makes sense when reality diverges from the plan.

## Non-goals
What this deliberately does not cover, and why. Cheap to write, and it
stops scope creep from being re-argued at phase 4.

## Decisions & rationale
One entry per significant decision: what was chosen, why, and what was
rejected and on what grounds. Recording rejected alternatives is what
keeps a settled debate settled — without it, phase 3 reopens phase 1.

## Assumptions
Only if there are any. Defaults you took without explicit discussion,
stated plainly so the user can correct them at a glance.

## Phases
### Phase 1 — <name>
- **Goal:** what this phase achieves, in one line
- **Changes:** files and areas touched
- **Verification:** the command to run, or how you'd know it worked
- **Done when:** the observable condition that closes the phase
- **Commit:** suggested message

### Phase 2 — <name>
...

## Phase dependencies
| Phase | Depends on | Blocks | Parallel with | Nature of the dependency |
|-------|-----------|--------|---------------|--------------------------|

## Open questions
| Question | What's unclear | Why it matters | Needed by |
|----------|---------------|----------------|-----------|
```

Drop sections that would be empty — an "Assumptions" heading over nothing is noise. Keep the order.

Name concrete files, modules, symbols, interfaces, data flows, and tests where the repository supports them. An invented path or a vague direction such as "update the backend" leaves the reader to redo the investigation you already did.

### What makes a phase atomic

Each phase should leave the repository in a state you'd be willing to commit and ship: it builds, tests pass, nothing is half-wired. That's the property that makes phases independently committable *and* independently revertable, which is the real prize — a phase that can't be backed out alone isn't a phase, it's a fragment.

Techniques that can buy this independence, when they fit the change:

- **Add before remove.** Introduce the new path alongside the old, migrate callers, delete the old — each step shippable, instead of one big-bang swap.
- **Land dormant code first.** New code that's tested but not yet called is a safe, reviewable commit.
- **Feature flags** when a behavior change has to go in before everything downstream is ready.
- **Separate mechanical from semantic.** A rename touching 200 files belongs in its own phase; mixed with logic changes, the diff becomes unreviewable and the logic change hides in the noise.

On sizing: aim for a single sitting's work and a diff someone would actually read. A goal with an "and" in it is often two phases. But don't shatter the work either — twelve phases where four would do imposes real per-phase cost in review, CI, and coordination.

### Verification steps

A verification step is only worth writing if it actually runs. Before citing one, confirm it against the repo: the script exists in `package.json` or the Makefile, its config file is present, and it isn't already failing for reasons unrelated to this work.

Naming `npm run build` in a project with no `tsconfig.json`, or a test command whose dependencies were never installed, hands the reader a check that fails no matter what they did. The cost isn't the wasted minute — it's that the verification line stops being trusted, and after that the phase boundaries aren't really guarded by anything.

Where nothing reliable exists, say so and give the best available substitute — a grep that should come back empty, a specific observation to make by hand — rather than a plausible-looking command you haven't confirmed. When a valid project command can't run in this checkout because setup is missing, label it as a post-setup gate rather than a check that runs now, and give one that does run now.

### Dependencies

A dependency is real when phase B cannot be written, or cannot pass its own verification, until phase A lands. Preferring to do A first is not a dependency — it's taste, and encoding taste as a constraint makes a plan serial that could have been parallel.

The "nature of the dependency" column is what makes the table worth having. "Phase 3 → phase 1" tells a reader nothing; "needs the schema migration from phase 1 to exist before its queries compile" tells them exactly how much room they have to reorder, split, or work around it.

### Open questions

A question belongs here only if the plan is still executable without its answer — it affects a later phase, or the answer can only come from doing the work (a measurement, a spike, a decision from someone outside the room).

If it blocks phase 1, it isn't an open question. It's a conversation, and it goes back through the gate in step 1. Watch for the temptation to file something here precisely because you'd rather not ask about it — that's the section quietly becoming a place to hide things.

For each one, give the reader enough to act: what specifically is unclear, what's at stake in getting it wrong, and which phase forces the answer.

## Step 4 — Stop at the plan

Producing the plan is the whole job. Don't begin implementing, and don't roll straight into "shall I start phase 1?" — the point of writing a plan is that it gets reviewed before any code moves. The user will say when to execute.

## Revising an existing plan

When the user comes back with changes: update the file in place if it's a file, re-render if it lived in chat.

Run the gate again on whatever changed — a new requirement can introduce new ambiguity, and it deserves the same treatment as the original. When a decision reverses, update its rationale entry rather than silently swapping the choice; the reader needs to know it was reconsidered, not just that it's different now. Open questions that got answered move into Decisions & rationale, with the answer and its reasoning.
