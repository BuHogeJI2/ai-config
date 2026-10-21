---
name: peer-chat
description: 'Hold a back-and-forth conversation with the Codex TUI running in the other pane of this agterm session''s split, as peers. Use when the user says "chat with codex", "talk to codex", "work with codex", "do this with codex", "build this with codex", "discuss this with codex", "ask codex what it thinks", or when a prompt arrives starting with "Chat from Codex:". Not for a one-shot task handed to Codex. When the user wants Codex to review Claude''s work, use codex-review instead.'
allowed-tools: Bash, Read, Grep, Glob, Write
---

# Peer chat, Claude side

Talk with Codex in the other pane of the split. The user can read both panes, but reading them is not
the outcome: the agent that started the conversation still gives the user a clear account of it.

Everything that touches the pane goes through `peer-chat.py` (on `PATH`). Never drive `agtermctl`
directly: the script checks the target agent, window, composer and caret, types the message in small
verified pieces and submits only after the last piece settles.

## Preconditions

The session needs a split with Codex already running in the other pane, started by the user. This skill
never starts an agent and never opens a pane. If the split is missing or Codex is not running there, say
so and stop.

## Sending

```bash
peer-chat.py --to codex --stdin <<'CHAT'
the message goes here, as one paragraph
CHAT
```

- Always pass the message on stdin through a quoted heredoc, never as an argument.
- The script collapses all whitespace to single spaces, so write one paragraph. For anything long or
  structured, write a file and send its path.
- Do not write `Chat from Claude:` yourself; the script adds the label.
- The default submit key is Return, which steers Codex's running turn. Use it for answers, corrections
  and stop signals in the conversation.
- Add `--queue` (Tab) for a new unit of work or a note that can wait. Tested: idle Codex starts it at
  once; busy Codex runs it as its own turn after the current one.
- If the script refuses because the pane is not running `codex`, and the user starts Codex through a
  wrapper, add `--target-command <wrapper name>` — only with a name the user gave you. Never guess one.

## Receiving

Codex's messages arrive as an ordinary prompt starting with `Chat from Codex: `. Read it as the next line
of a conversation, not as a task from the user.

A message that asks a question or reports a result that needs attention gets a reply through
`peer-chat.py` in the same turn. Text written only in this pane does not reach Codex. Closing
acknowledgements, "nothing further" and confirmations of finished work end the exchange without a reply.

## Conversation

- **Open with a brief.** Codex has none of this session's context. The first message gives the user's
  goal, the exact question, the scope and constraints, your current position and why, the files or
  evidence to read, and who may write. Put a long brief in a file and send its path.
- **Make each reply count.** Answer Codex's actual point. Say what you accept and why, and where the
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
   either agent's. Paths that hold the user's uncommitted changes go to nobody. To hand a path over, its owner stops and confirms first.
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

Do not poll or watch the other pane. Codex's reply wakes this session on its own; a watcher only creates a
deadlock. A reply is not promised either: never say Codex is "thinking about it" when all you know is that
the line was typed.

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
- Treat "Codex agreed" as the user's approval for anything.

## Manners

Plain language, short sentences. Quote Codex exactly when the wording matters or a claim is disputed;
otherwise a faithful summary is enough. Disagree when there is a disagreement: the useful output is a
located disagreement or a checked fact. Verify Codex's claims
about the code with your own tool call before repeating them to the user.
