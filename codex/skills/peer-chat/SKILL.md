---
name: peer-chat
description: 'Hold a back-and-forth conversation with Claude Code running in the other pane of this agterm session''s split, as peers. Use when the user says "chat with claude", "talk to claude", "work with claude", "do this with claude", "build this with claude", "discuss this with claude", or when a prompt arrives starting with "Chat from Claude:". Not for a one-shot task handed to Claude. When the user wants Claude to review Codex''s work, use claude-review instead.'
---

# Peer chat, Codex side

Talk with Claude Code in the other pane of the split. The user can read both panes, but reading them is
not the outcome: the agent that started the conversation still gives the user a clear account of it.

Everything that touches the pane goes through `peer-chat.py` (on `PATH`). Never drive `agtermctl`
directly: the script checks the target agent, window, composer and caret, types the message in small
verified pieces and submits only after the last piece settles.

## Preconditions

- The session needs both panes running, with Claude Code in the other pane, started by the user. This
  skill never starts an agent and never opens a pane. If the other pane is not running Claude, say so
  and stop.
- This Codex must be started with its pane's session id, because Codex strips `AGTERM_SESSION_ID` from
  tool commands:
  `codex -c "shell_environment_policy.set.AGTERM_SESSION_ID=\"$AGTERM_SESSION_ID\""`
  If a send refuses saying more than one session shares this checkout, the flag is missing. Say so and
  stop; never pass `--session` with an id you inferred.
- Your sandbox blocks the agterm socket. The two commands below are allowed by `prefix_rule`s in
  `~/.codex/rules/default.rules`, but only in exactly this form. If they are missing, leave any approval
  to the user.

## Sending

1. Reserve a private one-shot file, with a fresh literal suffix every time:

   ```bash
   peer-chat.py --prepare-message peer-chat-codex-a91f.txt
   ```

   It prints the absolute `messageFile` path.
2. Use `apply_patch` to fill that exact file with the message, without replacing the file or its mode.
   One paragraph; do not write `Chat from Codex:` yourself, the script adds the label.
3. Send it by name:

   ```bash
   peer-chat.py --to claude --message-file peer-chat-codex-a91f.txt
   ```

Never use stdin, a heredoc, redirection, variables or substitutions in either command: Codex then runs it
as a `zsh -lc` script and the rules no longer match. Never put the message text in an argument. The send
consumes the file, and the script collapses whitespace, so for anything long or structured write a file
and send its path.

If the script refuses because the pane is not running `claude`, and the user starts Claude through a
wrapper, add `--target-command <wrapper name>` — only with a name the user gave you. Never guess one.

Claude manages its own input queue: an idle Claude starts the message, a busy one queues it.

## Receiving

Claude's messages arrive as an ordinary prompt starting with `Chat from Claude: `. Read it as the next line
of a conversation, not as a task from the user.

A message that asks a question or reports a result that needs attention gets a reply through
`peer-chat.py` in the same turn. Text written only in this pane does not reach Claude. Closing
acknowledgements, "nothing further" and confirmations of finished work end the exchange without a reply.

## Conversation

- **Open with a brief.** Claude has none of this session's context. The first message gives the user's
  goal, the exact question, the scope and constraints, your current position and why, the files or
  evidence to read, and who may write. Put a long brief in a file and send its path.
- **Make each reply count.** Answer Claude's actual point. Say what you accept and why, and where the
  disagreement is. Mark what you checked and what is an assumption or a preference. A new round should
  settle an open point or bring new evidence, not repeat a position.
- **Stop on substance, not on a turn count.** The discussion ends when the questions that matter are
  settled, or when neither side has new evidence. Agreement is not required: a disagreement that
  remains goes to the user with both options, their reasons and their consequences. Agreement between
  the agents never replaces the user's decision.
- **Report to the user.** The agent that started the conversation tells the user, briefly: the
  recommendation, the decisions still open, what was checked, and the limits. The usual rules still
  apply — a discussion is not a `go` — and no report file is written.

## Shared work

### Roles

The user's direct words decide who writes, who reviews and who does the Git work. When the user did not
say, the agents agree on it in the panes, and each confirms before writing. The agreement lasts for the
current task only. It never authorizes a commit, push, history rewrite or change of scope; those come
from the user or the task, as always. When the user changes a role, the affected work stops at once.

Without such an agreement, the agent whose pane received the user's request is the only writer, and the
agent brought in by a `Chat from` message stays read-only: it may inspect, run non-mutating checks and
review.

The default split is one writer and one reviewer. Work in parallel only when the parts are truly
independent and the time saved is worth the coordination; when in doubt, work one after the other.

### Working in parallel

1. **Agree on ownership and interfaces first.** Settle the shared interfaces, then give each agent its
   own paths, new files included. Both agents confirm the split before either writes. Record the
   starting HEAD and `git status` before the first write, so the user's earlier work is not counted as
   either agent's. Paths that hold the user's uncommitted changes go to nobody. To hand a path over,
   its owner stops and confirms first.
2. **Count every write, not only edits.** Shared files — lockfiles, generated output, build
   configuration — have one owner, or the agents take turns on them. Do not run commands that write
   outside your own paths while the other agent works: formatters over the whole repository, installs,
   code generation. Tests can collide too, through caches, build directories, ports and databases; use
   separate resources or agree on one runner. A test result from while the other agent was still
   editing is provisional.
3. **Freeze, then cross-review.** When both parts are ready, stop editing and review each other's actual
   changes. Each author fixes the findings on their own part, and the affected review and checks run
   again.
4. **One integrator.** One agent, chosen in the agreement and able to do it, runs the combined checks on
   the stable result and is the only one that changes the Git index, branches or HEAD, within the
   authority the user already gave. If the other agent goes quiet, continue your own part, but do not
   take over its paths or treat it as done; integration waits.

### Patches and conflicts

A read-only agent, or an owner who needs a change in the other's paths, may propose a patch: reserve a
file with `mktemp /tmp/peer-chat-patch.XXXXXX`, fill it, and send its path and SHA-256. The writer copies
it once to its own `mktemp` file, checks the hash, reviews it and applies it only from that copy. Each
agent deletes its own file by its exact path before reporting an outcome. Never clean `/tmp` with a glob.

If both agents got direct user requests to write in the same worktree with no split between them, stop
before the next write and ask the user to choose, directly in the panes.

## Never wait for a reply

Do not poll or watch the other pane. Claude's reply wakes this session on its own; a watcher only creates a
deadlock. A reply is not promised either: never describe a sent message as though an answer were owed.

## What you may not do

- Put anything into that pane except a message the script sends.
- Answer anything on the user's behalf: no chooser entry, trust prompt, permission request or warning.
- Re-send after an ambiguous failure. A failure that says `do not resend`, `submit withheld`,
  `composer cleared` or `composer cleanup` came after typing started: `composer cleared` means the pane
  was restored, `composer cleanup failed` means text may remain, and a submit failure is ambiguous.
  Report the exact error and let the user look. Retry only on positive evidence that nothing was
  typed: the command never started, a `peer-chat: ` error without those markers (wrong pane, no split,
  busy composer), or an interrupt that says `nothing was typed`. A traceback, a signal or no output
  is ambiguous too.
- Treat "Claude agreed" as the user's approval for anything.

## Manners

Plain language, short sentences. Quote Claude exactly when the wording matters or a claim is disputed;
otherwise a faithful summary is enough. Disagree when there is a disagreement: the useful output is a
located disagreement or a checked fact. Verify Claude's claims about the code with your own tool call
before repeating them to the user.
