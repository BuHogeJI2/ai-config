---
priority: medium
created: 2026-09-28
where: [manifest.json, claude/skills/peer-chat/SKILL.md, codex/skills/peer-chat/SKILL.md]
blocked: README (phase 12) and second-device setup (phase 13) are not started
---

# Document a pinned install of peer-chat.py for a new machine

## Description

Both `peer-chat` skills call `peer-chat.py` as a bare command on `PATH`, but the helper is not in this
repo. On this machine `~/.local/bin/peer-chat.py` is a sh wrapper that runs
`~/.local/share/peer-chat/peer-chat.py` with `/opt/homebrew/bin/python3.12`. That file is byte-identical
to upstream `umputun/agterm` `cookbook/two-agent-chat/peer-chat.py` at commit
`3f0669328a4dc77b8a001a335e51d4247402dad8`, SHA-256
`102b4619e9b872f442c5987b7336461ecf5e635edefa41190878eac68f5b5fd9` (MIT). On a clone without it, both
skills are useless.

`requires.commands: ["peer-chat.py"]` in `manifest.json` makes `doctor` report a missing command, but it
proves only that something is on `PATH`, not that the wrapper, Python (3.10+) or agterm (0.24+) work.

## Reasoning

Medium: a second device silently gets two non-working skills, and the setup has several machine-specific
parts that are easy to forget.

## Possible fix

1. Record the upstream URL, full commit id and SHA-256 in the repo; never point at `master`.
2. Write a manual recipe: download the pinned file, verify the hash before installing, put it on `PATH`
   with a wrapper that uses a local Python 3.10+ (do not copy the Homebrew path literally), check
   `agtermctl`, add the two `peer-chat.py` prefix rules to `~/.codex/rules/default.rules`, and start Codex
   with the `AGTERM_SESSION_ID` flag.
3. No automatic download by `ai-config`. Vendoring the file stays a later option; it would need its own
   install and update design, since no allowed target lives in `~/.local`.
