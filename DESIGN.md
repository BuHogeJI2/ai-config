# AI Configuration Repository Design

## Purpose

This repository is the source of truth for portable personal configuration used by coding agents on multiple devices. It manages shared and agent-specific instructions and skills for Codex and Claude.

Application repositories remain responsible for their own architecture, build commands, technical decisions, and project-specific agent instructions.

### Scope of version 1

Version 1 manages:

- Skills.
- Global instructions.
- Migration of existing local skills and instructions.
- Validation (`doctor`), backup, restore, and uninstall.

Version 1 does not write agent settings, hooks, Codex rules, or MCP configuration. Claude instruction files under `~/.claude/rules/` are in scope; they are instructions, not permission rules. These are described under [Deferred to later versions](#deferred-to-later-versions) so the decisions are not lost.

## Core principles

### One source of truth

Shared skills and instructions are edited in this repository. Local agent directories contain symlinks or generated files managed from repository sources. There must not be two independently edited copies of the same shared skill.

Editing through a managed symlink is allowed because it edits the repository source directly. This was checked with Claude: an edit inside a linked skill directory changes the repository file and keeps the link, and an edit of a linked single file is redirected to the link target.

### Shared and agent-specific content

Content is classified by owner:

- `shared`: compatible with both Codex and Claude without agent-specific behavior.
- `codex`: uses Codex-specific instructions, configuration, tools, or behavior.
- `claude`: uses Claude-specific instructions, configuration, tools, or behavior.

An identical `SKILL.md` does not by itself prove identical behavior. A skill becomes shared only after validation in both agents.

### Global and project context

This repository contains portable personal preferences and reusable workflows. Application repositories contain project context, including architecture, commands, conventions, and repository-specific decisions.

Global instructions must not depend on one project or one checkout path.

### Safe synchronization

Git synchronization is deliberate. Before working on another device, pull the latest changes. Before publishing changes, inspect the diff and repository status.

Agent sessions and installation scripts must not automatically commit, pull, push, or resolve Git conflicts.

## Repository structure

The top level is split by owner. Each owner folder mirrors the part of the agent's home folder it manages, so ownership is visible from the path.

```text
ai-config/
├── README.md
├── DESIGN.md
├── .gitignore
├── manifest.json
│
├── shared/
│   ├── instructions.md
│   └── skills/
│
├── codex/
│   ├── instructions.md
│   └── skills/
│
├── claude/
│   ├── CLAUDE.md
│   └── skills/
│
├── scripts/
│   └── ai-config
│
└── tests/
    ├── fixtures/
    └── skills/
```

A folder is created only when it has content. Plain Claude content folders such as `claude/agents/`, `claude/rules/`, and `claude/output-styles/` are added the same way as skills when needed: one managed link per entry.

`prompts/` is not used because its purpose would be ambiguous. Reusable agent instructions belong in the instruction files; task-specific reusable workflows belong in `skills/`.

## Instructions

The default layout links Claude's instruction files, because Claude loads split instructions natively:

```text
~/.claude/CLAUDE.md        -> link to claude/CLAUDE.md
~/.claude/rules/shared.md  -> link to shared/instructions.md
```

When an agent is asked to change its global instructions, the edit goes to the repository source.

Codex has no equivalent, so the default layout generates only its file:

```text
~/.codex/AGENTS.md = shared/instructions.md + codex/instructions.md
```

The `compose` method may target any supported instruction file (`CLAUDE.md`, a Claude rules file, or `AGENTS.md`), never a skill folder. The generated file starts with a marker naming its sources, followed by the sources joined by one blank line; each source is read once, and its leading and trailing blank lines are dropped. The state file stores a hash of each source and of the generated output:

- On the first install, an existing file that equals the generated output without the marker is backed up and replaced. Any other existing content is a conflict.
- If the sources changed and the output did not, `install` regenerates it.
- If the output changed since it was generated, `install` reports a conflict and `diff` shows it. The local edit must be moved to a source file or discarded explicitly with `--replace-local`.
- `doctor` reports when the output is older than its sources, for example after `git pull`.
- The tool owns a generated file only while its bytes match a recorded hash. Before publishing, the new hash is saved together with the previous one, so an interrupted run never looks like a local edit.
- Changing an entry between `symlink` and `compose` replaces the managed link or the unedited generated file, with a backup.

An optional local Git `post-merge` hook may run `ai-config doctor`. It is read-only and is installed only by the user.

## Skills

### Install locations

- Codex personal skills are installed under `~/.agents/skills/<name>`.
- Claude personal skills are installed under `~/.claude/skills/<name>`.

The tool creates a separate symlink for each skill directory. It does not replace either complete `skills` directory, because those locations also contain bundled, synchronized, or application-managed skills.

### Legacy Codex location

Codex also loads skills from `$CODEX_HOME/skills` (`~/.codex/skills` by default). Its bundled skill creator and installer still write new skills there. Therefore:

- For every Codex target, the install planner also checks `~/.codex/skills/<name>`. If that copy is identical to the repository source, it is backed up and removed in the same run that creates the link under `~/.agents/skills`. If it differs, it is a conflict.
- `~/.codex/skills/.system` is never touched.
- `doctor` always inspects both Codex locations and reports skills created by Codex in the legacy location as unmanaged.

### Duplicate names

`doctor` checks for duplicate skill names across the user-level, system, and plugin locations an agent discovers skills from, not only the install target:

- Codex: `~/.agents/skills`, `~/.codex/skills` (including `.system`), and plugin skills.
- Claude: `~/.claude/skills` (including `synced/`), and plugin skills.

Both the directory name and the `name` field of `SKILL.md` are compared, without regard to letter case, because the default macOS file system is case-insensitive.

Project-level skill folders inside application repositories and administrator-wide locations are out of scope: they depend on the working directory or on machine policy, not on this repository.

### Content rules

Shared skills use only features supported by both agents. Agent-specific frontmatter, commands, paths, tool assumptions, and runtime behavior stay in their owner's folder.

A skill refers to its own files by paths relative to the skill folder, never by an install location such as `~/.claude/skills/<name>/...` or `~/.codex/skills/<name>/...`. Install locations differ between agents and change during migration.

Skills run through links, so a bundled script that checks whether it is the entry point must compare real paths. A Node check `import.meta.url === pathToFileURL(process.argv[1]).href` is false when the script is called through a linked folder, and the script silently does nothing; resolve `process.argv[1]` with `fs.realpathSync` first.

### Discovery check

Checked on 2026-09-28 with a throwaway skill and rules file installed by the tool (Codex CLI 0.157, Claude Code), each in a fresh headless session that saved no history:

- Codex loaded the linked skill from `~/.agents/skills` and ran its bundled script.
- Claude loaded the linked skill from `~/.claude/skills`, ran its bundled script, and followed a linked rules file in `~/.claude/rules/`.
- An edit of the skill's `SKILL.md` through the link, made with each agent's own file-editing tool, changed the repository file, and the links stayed links.
- Codex's sandbox checks the real path behind a link, so Codex can edit a linked skill only when the repository folder is writable for it (for example `--add-dir`, or approval in an interactive session).
- `install --prune` removed the links and `doctor` was clean afterwards.

### External skills

Some skills are installed and updated by an application, not written by the user. They stay application-managed on each device and are never adopted, copied into the repository, or linked by the tool. Today this is `agterm`, which the agterm app installs through Help ▸ Install Agent Skill… or as a plugin. A repository copy would go stale on every app update, and a reinstall from the app would write through the link into the repository.

Each skill may declare required CLI programs, MCP servers, and supported versions. Missing dependencies produce a clear diagnostic. The management tool never installs system dependencies.

An MCP check proves only that a server is configured, not that it works. Codex configuration is TOML, and Python 3.9 has no TOML parser, so `doctor` reads only plain `[mcp_servers.<name>]` headers. A spelling it does not understand is reported as "could not determine", never as missing.

## Manifest

`manifest.json` is the installation allowlist. Files are not installed merely because they exist in the repository, and `doctor` fails when a skill directory in the repository has no manifest entry.

The `external` list names skills that are application-managed (see [External skills](#external-skills)). `doctor` reports them as external instead of unmanaged, and warns if one of them is a link into this repository. `adopt` refuses them.

Each entry describes:

- A stable ID.
- The installation method: `symlink` or `compose`.
- Repository-relative sources. A source must stay inside the repository after symlinks are resolved.
- Local targets, written with a leading `~/`. Only these shapes are allowed:
  - `~/.agents/skills/<name>`
  - `~/.claude/skills/<name>`
  - `~/.claude/CLAUDE.md`
  - `~/.claude/rules/<name>.md`
  - `~/.codex/AGENTS.md`

  A target under `~/.codex/` is resolved through `$CODEX_HOME` when it is set. Any other target, including agent home folders, settings, and credential files, is rejected.
- Required dependencies, when applicable.

Example:

```json
{
  "version": 1,
  "external": ["agterm"],
  "entries": [
    {
      "id": "skill/backlog",
      "method": "symlink",
      "source": "shared/skills/backlog",
      "targets": ["~/.agents/skills/backlog", "~/.claude/skills/backlog"],
      "requires": { "commands": ["node"] }
    },
    {
      "id": "instructions/claude",
      "method": "symlink",
      "source": "claude/CLAUDE.md",
      "targets": ["~/.claude/CLAUDE.md"]
    },
    {
      "id": "instructions/codex",
      "method": "compose",
      "sources": ["shared/instructions.md", "codex/instructions.md"],
      "targets": ["~/.codex/AGENTS.md"]
    }
  ]
}
```

## State

The tool keeps its state outside the repository in `$XDG_STATE_HOME/ai-config/` (default `~/.local/state/ai-config/`):

```text
state.json   repository root, links created by the tool, generated-file hashes
lock         held while install, uninstall, or restore runs
backups/     see Backups
```

Because the state file records the repository root, `doctor` detects a moved checkout, and `install` can relink the affected links: they are provably owned by this repository.

## Management tool

One `scripts/ai-config` program provides all behavior through subcommands:

```text
scripts/ai-config doctor
scripts/ai-config diff <id>
scripts/ai-config install --dry-run
scripts/ai-config install [--prune] [--replace-local <id>]
scripts/ai-config adopt --agent <agent> --skill <name> --to <owner> [--replace-repo]
scripts/ai-config uninstall
scripts/ai-config restore <backup-id>
```

It is written in Python 3.9 or later using only the standard library, so it runs on any supported device without installing packages. The manifest and state files are JSON for the same reason.

### Installation behavior

Installation is planned first and applied second. The planner builds the full list of actions for every entry. If any action is a conflict, nothing is applied and the command exits with an error. `--dry-run` prints the same plan.

For each target, the planner chooses one action:

1. Target missing: create the link or generated file.
2. Target already correct: do nothing.
3. Target is a real local entry identical to the repository source: back it up and replace it with the link.
4. Target differs from the repository source: conflict.
5. Generated output was edited since the last install: conflict.
6. Target is a link to another path inside this repository (for example, a skill moved between owners): relink it.
7. Target is a link that the state file records as created by this tool and whose text still names the recorded source under the recorded old repository root (a moved checkout, even if the old checkout is gone): relink it.
8. Any other broken link, or a link that points outside this repository: conflict.
9. Link points into this repository but has no manifest entry (a removed or renamed skill): reported as a managed orphan and removed only with `--prune`.
10. Local content with no repository entry: reported as unmanaged and never changed.

For Codex targets, the planner also adds the action for the legacy copy in `~/.codex/skills` (see [Legacy Codex location](#legacy-codex-location)).

Two entries are identical when they contain the same relative paths, the same file contents, and the same executable bits. `.DS_Store` files are ignored. Nested symlinks are compared by their link text.

Conflicts are resolved explicitly:

- `diff <id>` shows the difference between the repository source and the local target.
- `install --replace-local <id>` backs up the local target and replaces it with the repository version.
- `adopt --replace-repo` copies the local version into the repository working tree. The change is reviewed with Git like any other edit.

### Writing safely

- Links and generated files are written to a temporary name in the same directory and then renamed into place.
- Right before the rename, the target is checked again. If it changed since planning, the command stops.
- A lock file prevents two runs at the same time.

### Adopting local content

`adopt` imports a local skill into the repository and adds its manifest entry:

- `--agent` selects where to look: both Codex locations for `codex`, `~/.claude/skills` for `claude`.
- `--to shared|codex|claude` selects the owner folder. The owner decides the targets: `shared` installs into both agents.
- It refuses external skills, forbidden files, and secrets.
- It never changes the agent homes and never commits.

### Uninstall behavior

Uninstall removes only links and generated files that the state file records as created by this tool and that still match what was created. It never removes an ordinary local file. Restoring a backup is a separate explicit action.

### Backups

Every replaced or removed local entry is backed up under `backups/<backup-id>/` in the state directory:

- The backup directory is created with mode `0700` and backup files with mode `0600`, whatever the source mode was. Original modes are recorded in the backup metadata.
- The last 5 backups of each target are kept. Older ones are removed after a successful install.
- `restore <backup-id>` puts the backup back and restores the original modes. If the target is a managed link, restore replaces it. If the target is ordinary local content that differs from the backup, restore reports a conflict.

## Configuration management

The complete `~/.codex` and `~/.claude` directories, and any of their subfolders, must never be linked to the repository. They mix authored configuration with credentials, histories, sessions, caches, databases, downloaded plugins, device state, and automatic permission grants.

In version 1 the tool never writes `~/.codex/config.toml`, `~/.claude/settings.json`, `~/.claude.json`, or any Codex rules file. `doctor` may read them to report missing dependencies of managed skills, such as a required MCP server.

These are never adopted, managed, or stored in the repository, in any version:

- Codex `rules/default.rules`: Codex appends a line to it each time a command is approved permanently, so it contains project-specific permission grants.
- Codex `[hooks.state]` tables: hook trust is approved on each device.
- Codex `[projects."<path>"]` trust tables.
- `~/.claude.json`: application-managed account and per-project state.
- Authentication, credential, history, session, and cache files.
- Permission, sandbox, approval, and environment keys, unless a later settings design allows a specific key with a written reason.

Plugin downloads and marketplace caches remain application-managed. The repository may later track a desired plugin list, but it must install plugins through their supported commands rather than copying caches.

## Security

The repository must not contain:

- Tokens, API keys, passwords, or authorization files.
- `.env` files or other secret-bearing local configuration.
- Session transcripts, prompt history, or confidential working data.
- SQLite databases, caches, logs, backups, attachments, or generated application state.
- Downloaded plugins, marketplace caches, or cloud-synchronized skills.
- Device identifiers, project trust records, or automatic permission grants.

The repository is public, so it must also not contain personal information: names, email addresses, user names, absolute home paths, host names, private project, employer, or client names, and private URLs. Instructions and skills state preferences and workflows, not who the user is or what they work on.

`.gitignore`, local validation, and secret scanning provide separate layers of protection. `adopt` runs the same checks before importing local content.

Scripts inside skills are executable capabilities. Their code, dependencies, requested permissions, and data access must be reviewable. Synced content must not silently grant broad filesystem, shell, network, or external-service access.

## Validation and testing

`doctor` checks:

- JSON syntax of the manifest and state file.
- Required `SKILL.md` metadata.
- Invalid classifications and skill directories missing from the manifest.
- Duplicate skill names across all discovery locations.
- External skills that are links into this repository.
- Missing referenced files, broken symlinks, and managed orphans.
- Generated output that is older than its sources or was edited locally.
- Script syntax and executable permissions, without writing files (no `__pycache__`).
- Declared CLI and MCP dependencies.
- Absolute home-directory paths and paths into the repository checkout in managed content.
- Common secret patterns and forbidden files.

Installation tests use the standard `unittest` module with temporary fake home directories and never modify real agent directories.

Discovery is checked statically by default: the link resolves, the frontmatter parses, and the name is unique across all locations.

Agent smoke tests verify skill discovery and a small representative task independently in Codex and Claude. They are opt-in because they write session history into the real agent homes. A temporary agent home has no authentication, and credentials must not be copied into it. Tests that invoke paid models or external services run only when explicitly requested.

Before the first real install on a device, one manual check confirms that:

- Codex loads a linked skill from `~/.agents/skills`.
- Claude loads a linked skill from `~/.claude/skills` and global instructions from `~/.claude/rules/shared.md`.

When continuous integration is added, workflows use minimal permissions and pin third-party actions to immutable revisions.

## Deferred to later versions

### Settings

A simple recursive merge into application-owned settings is not safe. When settings management is added, it uses three-way ownership:

- The state file lists each owned key path and the value last applied.
- For each key, the tool compares the repository value, the last-applied value, and the current local value. If only the repository changed, it applies the new value. If the local value changed, it reports a conflict. If a key was removed from the repository and the local value still equals the last-applied value, it removes the key.
- Arrays such as hook lists are owned as whole entries with a stable ID, such as the hook command. Managed entries are appended after existing ones, and existing order never changes, because Codex keys hook trust by array index.
- A static check rejects the forbidden keys listed under Configuration management.
- Writing TOML without losing comments and formatting will need a format-preserving library, which changes the dependency decision above.
- Agents rewrite their settings while running, so settings writes use the same recheck, atomic rename, and lock. Closing the agents first is recommended.

Hooks and status-line scripts (`codex/hooks/`, `claude/scripts/`) arrive together with settings, because they only take effect through settings.

### Paths in settings

Settings may refer only to installed locations, written as `"$HOME/..."` in double quotes, and never to the repository checkout path. Settings entries declare their dependencies the same way skills do, for example scripts installed by agterm.

### MCP servers

`~/.claude.json` is never merged. Claude MCP servers are added with `claude mcp add --scope user` after confirmation, or only reported by `doctor`. Codex `mcp_servers.*` entries use the settings ownership model, and their `env` values stay local.

### Codex rules

Curated Codex rules may be installed only as a link to one named file, such as `ai-config.rules`, never as a link to the rules folder. The file is treated as a permission grant: `doctor` shows it, and `install` asks for confirmation.

## Documentation and change history

`README.md` will explain installation, updating, adding a skill, resolving conflicts, restoring backups, and uninstalling managed configuration.

Ordinary changes are recorded in Git history. Incompatible changes to the manifest, installation behavior, or directory layout are documented separately when they occur.

## Initial migration notes

Skill migration finished on 2026-09-28 with these results:

- `agterm` is external. It stays app-managed and is not migrated.
- `commit-me` is one shared skill: the Claude text, the Codex frontmatter (a folded description, because the Claude one-line description was not valid YAML), and the Codex `agents/openai.yaml`.
- `backlog` stays two agent-specific skills for now, both with relative paths to their own files. Merging them is a backlog item.
- `peer-chat` is two agent-specific skills, one for each side of the chat. Both need `peer-chat.py` on `PATH`, a script from the agterm cookbook that is not in this repository; its entries declare it in `requires`, and README.md has the pinned install recipe.
- Codex `claude-review` and `task-plan` are counterparts to Claude `codex-review` and `plan`. They stay agent-specific.
- `styles-handling` was obsolete and was deleted, not migrated.
- `~/.claude/skills/synced/` is cloud-synchronized and never managed.

Instructions are migrated next, and these cases remain:

- `~/.codex/AGENTS.md` and `~/.claude/CLAUDE.md` state the same policies in different words. Migration chooses one wording for `shared/instructions.md`.
- `~/.claude/rules/` does not exist yet and is created by the first install.

Migration never assumes that similarly named skills should be merged. Divergent content remains unchanged until reviewed.

### One skill per step

Migration is not done in one run. Because the manifest is an allowlist, a skill that is not listed yet stays where it is, and `doctor` only reports it. Each skill moves in its own step and its own commit, and is tested in the real agents before the next one starts:

1. `doctor` is clean apart from unmanaged skills.
2. Review the skill, choose its owner, and plan any path fixes.
3. `adopt --agent <agent> --skill <name> --to <owner>`, then make the path fixes.
4. `install --dry-run` shows only this skill's actions.
5. `install`.
6. Use the skill on a small real task in a new session of each target agent.
7. `doctor` is clean for this skill.
8. Commit.

Global instructions move the same way: first the current files unchanged, then one shared policy per step.

### Rolling back one step

1. Remove the step from the repository: before the commit, restore `manifest.json` and delete the adopted folder; after the commit, `git revert` it.
2. `install --prune` removes the links that no longer have a manifest entry.
3. `restore <backup-id>` puts back each local copy that the step's install backed up.

## Platform assumption

The first implementation targets macOS and Linux. Windows support requires a separate decision about symlinks, path handling, and state-directory conventions.
