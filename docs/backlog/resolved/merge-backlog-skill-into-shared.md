---
priority: low
created: 2026-09-28
where: [claude/skills/backlog/SKILL.md, codex/skills/backlog/SKILL.md, claude/skills/backlog/scripts/backlog.mjs, codex/skills/backlog/scripts/backlog.mjs, manifest.json]
---

# Merge the two backlog skills into one shared skill

## Description

`backlog` was migrated as two agent-specific skills (`skill/backlog`, `skill/codex/backlog`) to keep
the migration small. The two copies carry the same rules and the same helper behavior, so every
change has to be made twice and the copies can drift apart.

The differences are small: `backlog.mjs` differs only in variable names and three comments;
`TEMPLATE.md` and `backlog.test.mjs` are identical. The Claude `SKILL.md` uses Claude-only
`argument-hint` and `$ARGUMENTS`, and names `AskUserQuestion` for picking an item; the Codex text is
a shorter rewrite with the same rules.

## Reasoning

Low: nothing breaks today; the cost is duplicated maintenance and possible drift.

## Possible fix

1. Take the Claude text and script as the base, as was done for `commit-me`.
2. Drop `argument-hint`; replace `$ARGUMENTS` with "the request selects the mode: `--list`,
   `--check [slug]` or `--add <description>`"; replace the `AskUserQuestion` step with a neutral
   short choice question.
3. Move it to `shared/skills/backlog` with both targets, remove the two agent entries, install with
   `--replace-local`, and test `/backlog --list` in Claude (arguments still arrive) and
   `$backlog --list` in Codex.
