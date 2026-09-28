# agterm + codex mechanics

The details behind the helper script. Read this when a review misbehaves or when you change
`scripts/codex-review.mjs`. Normal reviews never need it — and never load the `agterm` skill for this
flow.

## Transport: peer-chat.py

- `peer-chat.py` is on `PATH` (`~/.local/bin`). It is a launcher for the pinned upstream
  `umputun/agterm` cookbook script (commit `3f066932`, unmodified) in `~/.local/share/peer-chat/`,
  run with Python 3.12. The same script carries the `peer-chat` skill and both review skills, in both
  directions.
- Before typing, it checks that the session has a split, that the target pane runs `codex` (or
  `$PEER_CHAT_CODEX_COMMAND`), and that the composer is empty with the caret at column 2.
- Failures exit 1 (130 on interrupt) and differ only in their text, so `deliveryOutcome` reads the whole
  process result. It clears a round for a re-send only on positive evidence that nothing was typed: the
  program never started (ENOENT/EACCES), a handled `peer-chat: ` error with none of the after-typing
  markers (`do not resend`, `submit withheld`, `composer cleared`/`composer cleanup`), or an interrupt
  that says `nothing was typed`. A signal, a traceback, empty output or any marker leaves the round
  `sending`, and it is never re-sent. This relies on the pinned script naming a marker on every handled
  after-typing failure; check that again after each upstream update.
- `--queue` submits with Tab. Tested on codex-cli 0.157.0: idle Codex starts the message at once;
  busy Codex shows it under "Queued follow-up inputs" and runs it as its own turn afterwards. Return
  would steer the running turn instead.

## Round states in meta.json

`rounds[N].state`: `sending` → `sent` → `answered`. `send` refuses a round that has any state, a round
whose previous round is not `answered`, and a round whose `answer-N.md` already exists. `answer`
accepts only a regular, non-empty `answer-N.md` written after the round was sent; it also settles a
`sending` round, since a reply proves delivery. Exec mode goes `sending` → `answered` inside one call
and clears the state when `codex exec` fails, because a headless run leaves nothing behind.

## Codex sandbox facts

- Codex strips `AGTERM_SESSION_ID` from its tool subprocesses. Start it with
  `codex -c "shell_environment_policy.set.AGTERM_SESSION_ID=\"$AGTERM_SESSION_ID\""` so its sends find
  their session; without it `peer-chat.py` refuses when two sessions share one checkout.
- The workspace-write sandbox blocks the agterm control socket. Codex's two literal commands
  `peer-chat.py --prepare-message …` and `peer-chat.py --to claude --message-file …` are allowed by
  `prefix_rule`s in `~/.codex/rules/default.rules`; any other form (heredoc, wrapper) is not matched.
- The sandbox can write `$TMPDIR`, but not a repo it was not started in, which is why every agterm
  review folder lives there.

## Headless (exec) facts

- `codex exec` has no `-a/--ask-for-approval`; that flag is interactive-CLI only. `--skip-git-repo-check`
  is likewise `exec`-only.
- Round 1 reads the thread id from the `thread.started` JSON event; later rounds use
  `codex exec resume <id>` with `sandbox_mode="read-only"`.
