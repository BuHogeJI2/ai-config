---
name: task-plan
description: Create phased, independently committable implementation or refactoring plans for codebase changes, grounded in prior discussion and repository evidence. Use whenever the user asks for a codebase plan, implementation plan, roadmap, migration sequence, phased approach, ordered steps, or an approach to a refactor, including requests such as "write up a plan," "break this into phases," or "what is the order of work?" Also use when revising or extending an existing codebase plan or when a design discussion has converged and the requested next artifact is a plan. Apply this skill whether the interaction is in Plan mode or any other mode.
---

# Task Plan

Produce a handoff artifact that a teammate or a fresh session can execute without recovering the original conversation. Ground it in repository evidence, make assumptions visible, and stop rather than planning around material ambiguity.

Apply the same workflow in every interaction mode. Do not treat an internal plan, task list, or planning tool state as a substitute for the user-facing plan artifact.

## Scale the ceremony

Match the structure to the change. Use phased plans and dependency tables for work spanning multiple commits, areas, or sequencing risks. For a small, obviously ordered change, say that it does not need full ceremony and provide only:

- **Task:** what changes and why
- **Approach:** the ordered implementation steps
- **Verification:** how to prove it works

Optimize for clarity, not document size.

## 1. Pass the readiness gate

Inspect the relevant code and project instructions before asking questions. Use repository conventions, nearby implementations, configuration, and existing tests to resolve apparent ambiguity.

Then build a private decision ledger and classify every plan-shaping decision:

- **Decided:** Settled by the discussion or an explicit user constraint. Preserve the reasoning for the plan.
- **Assumed:** Not explicitly discussed, but repository conventions leave one unsurprising answer. Expose it in the plan.
- **Blocking:** Two or more defensible answers remain, and the choice changes implementation, phase boundaries, or the definition of done.

Classify a choice as blocking when it could reasonably surprise the user or when another competent engineer with the same context could choose differently.

Treat unresolved externally observable contracts, security boundaries, migration or cutover strategy, persistence semantics, and concurrency models as blocking unless the discussion or a clear repository convention settles them. Do not downgrade these choices to assumptions merely because one option is easy to invent.

Do not write the plan while any blocking item remains. Return to discussion, ask only the questions that survived repository inspection, explain what each answer changes, and recommend an option where appropriate. Resume planning after the blockers are resolved.

Do not manufacture uncertainty about settled choices. When invoked with little context, inspect first, then ask about genuine blockers rather than filling gaps with plausible guesses.

## 2. Choose the destination

- Write to a path or external location only when the user explicitly names it.
- Otherwise, render the plan in the conversation.
- Do not ask where to save it when no destination was requested.

## 3. Write the plan

Assume the reader has no shared context. Keep this section order and omit empty sections:

```markdown
# Plan: <short title>

## Task
Describe the problem, motivation, and intended outcome before the solution.

## Non-goals
State what the work deliberately excludes and why.

## Decisions & rationale
Record each significant choice, why it was selected, and which alternatives
were rejected and why.

## Assumptions
List defaults taken without explicit discussion so they are easy to correct.

## Phases
### Phase 1 — <name>
- **Goal:** <one-line outcome>
- **Changes:** <specific files, symbols, and areas>
- **Verification:** <confirmed command or observable check>
- **Done when:** <observable completion condition>
- **Commit:** <suggested commit message>

### Phase 2 — <name>
...

## Phase dependencies
| Phase | Depends on | Blocks | Parallel with | Nature of the dependency |
|-------|------------|--------|---------------|--------------------------|

## Open questions
| Question | What's unclear | Why it matters | Needed by |
|----------|----------------|----------------|-----------|
```

Lead with the problem and motivation so the reader can reevaluate the approach when reality changes. Preserve rejected alternatives in **Decisions & rationale** so settled debates do not silently reopen.

Name concrete files, modules, symbols, interfaces, data flows, and tests when repository evidence supports them. Avoid invented paths or vague directions such as "update the backend."

### Make each phase atomic

Make every phase independently committable and revertible. Leave the repository buildable, testable, and shippable at each boundary; do not leave half-wired behavior.

Use these patterns when useful:

- Add a new path before removing the old one.
- Land tested dormant code before wiring it into production behavior.
- Use feature flags when behavior must land before downstream work is ready.
- Separate mechanical changes from semantic changes.

Size a phase for one focused working session and a reviewable diff. Split goals joined by a substantial "and," but do not create ceremony through excessive fragmentation.

### Confirm verification steps

Verify every command against the repository before citing it. Confirm that the script, configuration, and dependencies exist and that the check is not already failing for unrelated reasons.

If no reliable automated check exists, say so and give the best available substitute, such as a precise manual observation or a search that should return no matches. When a valid project command cannot run in the inspected checkout because setup is missing, label it as a post-setup gate rather than a currently runnable check and provide a check that is runnable now. Never invent a plausible command.

### Record real dependencies

Declare a dependency only when a later phase cannot be implemented or cannot pass verification until an earlier phase lands. Do not encode preferred ordering as a hard dependency.

Explain the dependency's nature precisely enough that a reader can decide whether to reorder, split, or work around it.

### Keep open questions non-blocking

Include only questions that do not prevent execution from starting, such as decisions needed by a later phase, measurements produced by a spike, or choices owned outside the team.

Move any question that blocks the first executable phase back through the readiness gate. For each remaining open question, state what is unclear, what is at stake, and when the answer becomes necessary.

## 4. Stop at the plan

End after delivering the plan. Do not implement any phase, modify code beyond an explicitly requested plan file, or immediately ask to begin phase 1. Let the user review the artifact and decide the next action.

## Revise an existing plan

Update a file in place when the plan is file-backed; otherwise, render the revised plan in the conversation.

Run the readiness gate again for every changed requirement. When a decision reverses, update its rationale and record why it changed. Move answered open questions into **Decisions & rationale** instead of silently deleting them.
