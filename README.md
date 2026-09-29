# ai-config

Personal skills and global instructions for [Codex](https://developers.openai.com/codex) and
[Claude Code](https://code.claude.com), kept in one repository and linked into both agents on every
machine by a small tool, `scripts/ai-config`.

The repository is public. You are welcome to use any skill in it under the [MIT license](LICENSE).

## Use a single skill

Each skill is a folder with a `SKILL.md`. Copy the folder you want into your agent's skill location:

| Folder | Works in | Copy to |
|---|---|---|
| `shared/skills/<name>` | both agents | `~/.claude/skills/<name>` and/or `~/.agents/skills/<name>` |
| `claude/skills/<name>` | Claude Code | `~/.claude/skills/<name>` |
| `codex/skills/<name>` | Codex | `~/.agents/skills/<name>` |

Copy the whole folder, with its scripts, references and `agents/` metadata, and do not overwrite a skill
of yours with the same name. Start a new agent session after copying. Read the skill's `SKILL.md`
first: some skills need [extra programs](#requirements).

Do not run `scripts/ai-config install` on your machine as it is. It installs everything in
`manifest.json`, including the owner's global instructions, which would take the place of your own
`~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`. To manage your own setup with the tool, fork the
repository and make it yours:

- Delete the skill folders you do not want together with their manifest entries. `doctor` reports a
  skill folder that has no entry.
- Replace `claude/CLAUDE.md`, `codex/instructions.md` and `shared/instructions.md` with your own, or
  delete the three `instructions/...` entries to leave your global instructions alone.

## Skills

| Skill | Agent | What it does |
|---|---|---|
| `commit-me` | both | Commits only when asked, with a message in the repository's own style. |
| `planning` | both | Writes a phased implementation plan once a discussion has settled. |
| `codex-review` | Claude | Asks Codex for an independent review, then checks each finding. |
| `claude-review` | Codex | Asks Claude for an independent review, then checks each finding. |
| `backlog` | both | Files out-of-scope findings into a repo-local backlog and checks them later. |
| `peer-chat` | Claude, Codex | Lets Claude and Codex talk to each other in an agterm split. |

`peer-chat` has one copy per agent, because each copy describes its own side of the chat.

## How it works

```text
shared/
  instructions.md        rules for both agents
  skills/<name>/         skills for both agents
claude/
  CLAUDE.md              Claude-only instructions
  skills/<name>/
codex/
  instructions.md        Codex-only instructions
  skills/<name>/
manifest.json            what is installed, and where
scripts/ai-config        the tool (Python 3.9+, standard library only)
```

`manifest.json` is the list of everything the tool installs. A folder that is not listed is not
installed. `install` puts these into the agent homes:

| Installed file | Kind | Source |
|---|---|---|
| `~/.claude/skills/<name>` | link | `claude/skills/<name>` or `shared/skills/<name>` |
| `~/.agents/skills/<name>` | link | `codex/skills/<name>` or `shared/skills/<name>` |
| `~/.claude/CLAUDE.md` | link | `claude/CLAUDE.md` |
| `~/.claude/rules/shared.md` | link | `shared/instructions.md` |
| `~/.codex/AGENTS.md` | generated file | `shared/instructions.md` + `codex/instructions.md` |

Codex loads one global instruction file, so the tool combines both sources into `AGENTS.md`, with a
first line saying so. A global `AGENTS.override.md`, if you have one, takes precedence over it.

Codex also loads skills from its older location, `~/.codex/skills`. When a skill moves to
`~/.agents/skills`, `install` backs up and removes the old copy there, so Codex does not see it twice.

Before `install` replaces or removes anything, it makes a backup. The tool never touches files it does
not manage: other skills, agent settings, and the skills of apps such as agterm stay as they are.

## Requirements

The tool needs macOS or Linux, Git, and Python 3.9 or newer, and nothing else.

Some skills need more:

- Claude Code and/or Codex, and both for the review and `peer-chat` skills.
- Node.js, for the skills with scripts: `backlog`, `codex-review`, `claude-review`.
- For `peer-chat`, and for the in-pane mode of the two review skills: the
  [agterm](https://github.com/umputun/agterm) terminal 0.24 or newer with `agtermctl`, and `peer-chat.py`
  on `PATH`. Without agterm the review skills run the other agent headless instead.

`install` does not check these. `scripts/ai-config doctor` reports a program that a manifest entry
requires and that is missing from `PATH`.

A machine with only one agent can install for that agent alone (see
[Install on a new machine](#install-on-a-new-machine)). This does not remove what a skill needs: the
Codex `claude-review` skill still runs Claude, and `peer-chat` still needs a Claude pane.

### Install peer-chat.py

`peer-chat.py` comes from the agterm cookbook and is not part of this repository. Install the pinned,
checked version. It needs Python 3.10 or newer.

Download it to a temporary file, check it, and only then put it in place, so a failed download never
replaces a working copy:

```sh
mkdir -p ~/.local/share/peer-chat ~/.local/bin
cd ~/.local/share/peer-chat
curl -fsSLo peer-chat.py.new https://raw.githubusercontent.com/umputun/agterm/3f0669328a4dc77b8a001a335e51d4247402dad8/cookbook/two-agent-chat/peer-chat.py
echo "102b4619e9b872f442c5987b7336461ecf5e635edefa41190878eac68f5b5fd9  peer-chat.py.new" | shasum -a 256 -c && mv peer-chat.py.new peer-chat.py
```

On Linux, use `sha256sum -c` in place of `shasum -a 256 -c`. If the check does not print
`peer-chat.py.new: OK`, the file is not moved; delete `peer-chat.py.new` and stop.

Put a launcher in `~/.local/bin` that runs it with a Python 3.10 or newer. Replace `python3.12` with the
interpreter you have:

```sh
printf '#!/bin/sh\nexec python3.12 "$HOME/.local/share/peer-chat/peer-chat.py" "$@"\n' > ~/.local/bin/peer-chat.py
chmod +x ~/.local/bin/peer-chat.py
export PATH="$HOME/.local/bin:$PATH"
command -v peer-chat.py
peer-chat.py --help
```

`export` lasts only for this shell. If `~/.local/bin` is not on your `PATH` yet, add the same `export`
line to your shell configuration, such as `~/.zshrc` or `~/.bashrc`.

Codex needs two more things:

- Its sandbox blocks the agterm socket. Allow the two commands the `peer-chat` skill uses by adding
  these lines to `~/.codex/rules/default.rules`:

  ```text
  prefix_rule(pattern=["peer-chat.py", "--prepare-message"], decision="allow")
  prefix_rule(pattern=["peer-chat.py", "--to", "claude", "--message-file"], decision="allow")
  ```

- Codex hides `AGTERM_SESSION_ID` from its commands. Start it inside agterm with:

  ```sh
  codex -c "shell_environment_policy.set.AGTERM_SESSION_ID=\"$AGTERM_SESSION_ID\""
  ```

## Install on a new machine

Clone the repository anywhere and keep it there: the installed links point into this folder.

```sh
git clone https://github.com/BuHogeJI2/ai-config.git
cd ai-config
```

If the machine has only one of the agents, name it with `--agents`:

```sh
scripts/ai-config doctor --agents codex
scripts/ai-config install --dry-run --agents codex
scripts/ai-config install --agents codex
```

Use `claude` for a Claude-only machine. Nothing is written to the other agent's folder. An `install`
whose plan has no conflict saves the choice for this machine, and later commands use it without the
flag. A dry run or an install stopped by a conflict saves nothing, so keep `--agents` on every command,
including the conflict steps below, until an install goes through.

Without `--agents` and without a saved choice, the tool works for both agents:

```sh
scripts/ai-config doctor
scripts/ai-config install --dry-run
```

`doctor` changes nothing. It lists problems, skills the repository does not manage yet, and what
`install` would do. `install --dry-run` prints the plan:

```text
create         ~/.claude/skills/planning -> shared/skills/planning
create         ~/.codex/AGENTS.md
conflict       ~/.claude/CLAUDE.md: local content differs from the repository (see: ai-config diff instructions/claude)
```

If the plan has a conflict, `install` changes none of the installed files (it may still create its own
state folder). [Resolve each conflict](#resolve-a-conflict),
then run:

```sh
scripts/ai-config install
```

Start new agent sessions to load the skills and instructions.

## Resolve a conflict

A conflict means `install` cannot safely put a file in place. The common kind is local content that
differs from the repository, or a link that points somewhere else. Look at the difference first; the id
is in the conflict line:

```sh
scripts/ai-config diff instructions/claude
```

Then choose one side:

- Keep the repository version. Check the plan first, because `--replace-local` applies to every target
  of the entry, including an old Codex copy in `~/.codex/skills`. Each local copy is backed up:

  ```sh
  scripts/ai-config install --dry-run --replace-local instructions/claude
  scripts/ai-config install --replace-local instructions/claude
  ```

- Keep the local version of a skill folder. This copies it over the repository copy; commit it, then
  install:

  ```sh
  scripts/ai-config adopt --agent claude --skill planning --to shared --replace-repo
  ```

  `adopt` works only on real skill folders. For an instruction file, copy the lines you want to keep
  into the repository file by hand, then use `--replace-local`.

`--replace-local` overrides only differing content and foreign or broken links. Other conflicts, such
as a missing repository source, a target that cannot be read, or a target whose location resolves
somewhere unsafe, need their cause fixed first; the conflict line names it.

## Everyday use

Change skills and instructions in the repository, then commit and push.

- **Skills** are links, so an edit is live at once, in both agents. An agent that edits an installed
  skill through its link also changes the repository file. Codex can do that only when its sandbox may
  write the repository folder, for example `codex --add-dir <repository path>`.
- **Claude instructions** (`claude/CLAUDE.md`, `shared/instructions.md`) are links too. Edit them in the
  repository; a new session loads the change.
- **Codex instructions** (`codex/instructions.md`, `shared/instructions.md`) reach Codex only through the
  generated `~/.codex/AGENTS.md`. Run `scripts/ai-config install` after a change. Never edit
  `~/.codex/AGENTS.md` itself: `install` reports the edit as a conflict.

New sessions pick up changes; a running session keeps what it loaded at start.

## Update another machine

```sh
git pull
scripts/ai-config doctor
scripts/ai-config install
```

`doctor` reports when the generated `~/.codex/AGENTS.md` is older than its sources. `install` links new
skills and regenerates the file. Both use the agents saved on this machine.

When a pull removed or renamed a skill or an instruction entry, `doctor` reports the old target as an
orphan. Check the plan, then remove the old targets:

```sh
scripts/ai-config install --dry-run --prune
scripts/ai-config install --prune
```

`--prune` removes, with a backup, only what the tool created: links into this repository, and a
generated instruction file that is still unedited. An old plain copy of a skill, left from before this
repository managed it, stays in place; `doctor` lists it as unmanaged. Back it up, then remove it
yourself.

### Change the agents

To add an agent, name the complete new set:

```sh
scripts/ai-config install --dry-run --agents codex,claude
scripts/ai-config install --agents codex,claude
```

To stop using one, name the agent you keep and add `--prune`:

```sh
scripts/ai-config install --dry-run --agents codex --prune
scripts/ai-config install --agents codex --prune
```

This removes, with a backup, the other agent's links into this repository and its unedited generated
file. Edited files and your own content stay. Without `--prune` nothing is removed, and `doctor` reports
those links as orphans with "agent disabled".

## Add a skill

Take a skill you already have in an agent:

```sh
scripts/ai-config adopt --agent claude --skill my-skill --to shared
```

`adopt` copies it into `shared/`, `claude/` or `codex/` and adds its manifest entry. Or write a new one
in `<owner>/skills/<name>/` and add the entry yourself:

```json
{
  "id": "skill/my-skill",
  "method": "symlink",
  "source": "shared/skills/my-skill",
  "targets": ["~/.agents/skills/my-skill", "~/.claude/skills/my-skill"],
  "requires": { "commands": ["node"] }
}
```

A Claude-only skill has only the `~/.claude/skills/` target, and a Codex-only skill only the
`~/.agents/skills/` target. `requires` is optional. Then:

```sh
scripts/ai-config install --dry-run
scripts/ai-config install
```

Try the skill in a new session of each agent before you commit it.

Rules for skill content:

- A skill names its own files by paths relative to its folder, never by an install location such as
  `~/.claude/skills/<name>/`.
- A shared skill uses only what both agents support. Codex metadata goes in `agents/openai.yaml`; Claude
  ignores it.
- Skills run through links. A script that checks whether it is the entry point must compare real paths:
  in Node, resolve `process.argv[1]` with `fs.realpathSync` before comparing it with `import.meta.url`.
- No secrets, and nothing private: this repository is public.

To remove a skill, delete its folder and manifest entry, then run
`scripts/ai-config install --prune` to remove its links.

## Backups and restore

Every file `install` replaces or removes is backed up first, under
`~/.local/state/ai-config/backups/` (or `$XDG_STATE_HOME/ai-config/backups/`). The newest five backups
of each target are kept.

```sh
scripts/ai-config restore              # list the backups
scripts/ai-config restore <backup-id>  # put one back
```

`restore` replaces a managed link or generated file, but refuses to overwrite other local content. The
restored target is no longer managed. While its manifest entry is still there, the next `install`
replaces the restored copy again (with a backup) if it equals the repository version, and reports a
conflict if it differs. To keep it, remove the entry first.

`restore` does not look at the saved agents, so it can put back a file of an agent this machine no longer
uses. A restored link into this repository is removed again by the next `install --prune`; a restored
copy stays.

The state and backups live outside the repository and are never committed.

## Uninstall

```sh
scripts/ai-config uninstall
```

This removes the links and generated files the tool created, as long as they are unchanged. A changed
one is kept and reported. `uninstall` makes no new backups, since everything it removes can be created
again from the repository. Earlier backups are not restored; use `restore` for that.

## Details

- `$CODEX_HOME` is used in place of `~/.codex` when it is set.
- Tests: `python3 -m unittest discover -s tests -t .`
- [DESIGN.md](DESIGN.md) has the full design, [docs/plans/](docs/plans/) the implementation plan, and
  [docs/backlog/](docs/backlog/) the open issues.
