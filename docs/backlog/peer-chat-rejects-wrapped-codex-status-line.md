---
priority: medium
created: 2026-11-16
where: [README.md, claude/skills/peer-chat/SKILL.md]
---

# peer-chat.py cannot send to Codex when its status line wraps

## Description

`peer-chat.py --to codex` refuses every send with "target composer prompt is not recognisable
(shell mode, disabled input, a trailing modal or status row, or an unknown prompt glyph); nothing was
typed", although the Codex composer is empty and ready (`› Ask Codex to do anything`). Seen on
2026-11-16 in a local repo, four sends in a row, each after 5 retries.

Cause: the Codex status line (`~/path/to/project · develop · <model> · Context … · weekly … · <thread
title>`) was too long for the pane width, so the thread title wrapped onto a second row. The footer
then had three rows: status, wrapped status, shortcut hint. `trailing_input_block` in the pinned
script (agterm cookbook at `3f066932`, installed per README.md) strips at most two footer rows
(blank row + `CODEX_FOOTER_RE` + footer/notice), so the wrapped row was read as the composer and
`CODEX_PROMPT_RE` did not match. The pane being left or right is not involved.

Workaround: widen the Codex pane, shorten the thread title, or trim the status line until it fits
on one row.

## Reasoning

Medium: it blocks peer chat entirely whenever the pane is narrow or the thread title is long, and
the error points at the wrong causes (modal, shell mode). It fails closed, so no text is lost.

## Possible fix

- Report it upstream (umputun/agterm, `cookbook/two-agent-chat/peer-chat.py`) with the pane text,
  or check whether a newer cookbook version already handles wrapped footers, then re-pin README.md.
- Upstream fix idea: treat the run of two-space-indented rows below the composer's blank padding as
  footer, not only the last one or two. Keep failing closed when a row could be a wrapped draft.
- Meanwhile, add the workaround to `claude/skills/peer-chat/SKILL.md` next to the error list.
