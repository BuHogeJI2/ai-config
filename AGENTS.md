# ai-config

This repository holds the owner's Codex and Claude Code skills and global instructions, and the tool
that installs them, `scripts/ai-config`. [README.md](README.md) explains the layout and the commands,
[DESIGN.md](DESIGN.md) the design and its reasons.

## The repository is public

Never add secrets, credentials, `.env` files, absolute home paths, or private project, employer, client,
or host names. This applies to skills, instructions, docs, tests, and commit messages. Test fixtures use
placeholder paths such as `/Users/someone`. `doctor` looks for common secret patterns, and for home
paths only in the `shared/`, `claude/` and `codex/` trees; it is not a full privacy check.

## The tool

- Python 3.9, standard library only. Do not add dependencies or syntax newer than 3.9.
- `scripts/ai-config` is the entry point; the code is in `scripts/ai_config/`.
- Run the tests with `python3 -m unittest discover -s tests -t .` from the repository root.
- Tests use temporary fake homes (`tests/helpers.py`). A test must never read or write the real agent
  homes.
- Keep `DESIGN.md` in step with behavior changes.

## Commands and the real agent homes

`doctor`, `install --dry-run`, `diff`, and `restore` without an id only read. Run them freely.

`install`, `install --prune`, `install --replace-local`, `restore <id>`, and `uninstall` change the real
`~/.claude`, `~/.agents`, and `~/.codex` folders. `adopt` copies local skills into the repository. Run
these only when the user asks, and show `install --dry-run` first.

## Editing skills and instructions

- Edit the sources in this repository. The installed skills, `~/.claude/CLAUDE.md`, and
  `~/.claude/rules/shared.md` are links to them.
- Never edit `~/.codex/AGENTS.md`: it is generated from `shared/instructions.md` and
  `codex/instructions.md`, and `install` regenerates it.
- A rule for both agents goes in `shared/instructions.md`, and one for a single agent in
  `claude/CLAUDE.md` or `codex/instructions.md`. A rule is stated in one file only.
- Follow the skill content rules in README.md: relative paths to the skill's own files, only features
  both agents support in `shared/`, real-path entry-point checks in scripts.
- A new skill needs a manifest entry.
- A test of a skill or instruction change in a fresh agent session (for example
  `claude -p --no-session-persistence`, `codex exec --ephemeral`) calls a paid model. Propose it and run
  it only when the user agrees. Documentation-only changes need no model test.

## Backlog

Out-of-scope findings go to `docs/backlog/` through the `backlog` skill.

## Commits

Commit messages are one subject line: `feat:` for tool or skill changes, `docs:` for documentation only,
`test:` when the diff is only tests.
