# agterm mechanics

Read this only when debugging or changing the helper.

## Transport: peer-chat.py

`peer-chat.py` on `PATH` (`~/.local/bin`) is a launcher for the pinned upstream `umputun/agterm` cookbook
script (commit `3f066932`, unmodified) in `~/.local/share/peer-chat/`, run with Python 3.12. Both review
skills and the `peer-chat` skill use it, in both directions.

Before typing, it checks that the session has a split, that the target pane runs `claude` (or
`$PEER_CHAT_CLAUDE_COMMAND`), and that the composer is empty with the caret at column 2. A refusal at that
point, or while resolving the target, is safe to send again. Failures exit 1 (130 on interrupt) and differ
only in their text. In the pinned script every handled failure after typing started names `do not resend`,
`submit withheld` or `composer cleared`/`composer cleanup`; check that again after each upstream update. A
round is cleared for a re-send only on positive evidence: the command never started, a handled `peer-chat: `
error without those markers, or an interrupt that says `nothing was typed`. A signal, a traceback or no
output stays unknown.

## Why the helper does not send

The Codex workspace-write sandbox blocks the agterm control socket. Only the two literal commands matched by
`~/.codex/rules/default.rules` run outside it:

- `peer-chat.py --prepare-message <name>` — the helper runs this itself; it only creates a 0600 file in a
  0700 spool under `$TMPDIR`, which the sandbox allows. The helper then writes the pointer into it,
  truncating in place so the mode stays.
- `peer-chat.py --to claude --message-file <name>` — Codex runs this. A wrapper, heredoc or variable in the
  command makes Codex evaluate it as a shell script, and the rule no longer matches.

Codex strips `AGTERM_SESSION_ID` from tool subprocesses. Start Codex with
`codex -c "shell_environment_policy.set.AGTERM_SESSION_ID=\"$AGTERM_SESSION_ID\""`; without it
`peer-chat.py` falls back to matching the checkout and refuses when two sessions share it.

## Round states in meta.json

`rounds[N].state`: `sending` → `sent` → `answered`. `send` refuses a round with any state, a round whose
previous round is not `answered`, and a round whose `answer-N.md` exists. `sent`/`unsent` settle a
`sending` round after the peer-chat command. `answer` accepts only a regular, non-empty `answer-N.md`
written after the round was sent, and it also settles a round left `sending` by an ambiguous failure, since a
reply proves delivery. Exec mode goes `sending` → `answered` in one call and clears the state when
`claude -p` fails.

## Headless (exec) facts

`claude -p --output-format json --permission-mode plan --permission-prompts none`, round 1 with a fixed
`--session-id`, later rounds with `--resume`. `CLAUDECODE` is removed from the environment so this Claude does
not think it is nested in another one.
