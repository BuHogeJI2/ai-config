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

Version 1 does not write agent settings, hooks, rules, or MCP configuration. These are described under [Deferred to later versions](#deferred-to-later-versions) so the decisions are not lost.

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

Claude loads split instructions natively, so nothing is generated for Claude:

```text
~/.claude/CLAUDE.md        -> link to claude/CLAUDE.md
~/.claude/rules/shared.md  -> link to shared/instructions.md
```

When an agent is asked to change its global instructions, the edit goes to the repository source.

Codex has no equivalent, so only its file is generated:

```text
~/.codex/AGENTS.md = shared/instructions.md + codex/instructions.md
```

The generated file starts with a marker saying it is generated and naming its sources. The state file stores a hash of each source and of the generated output:

- If the sources changed and the output did not, `install` regenerates it.
- If the output changed since it was generated, `install` reports a conflict and shows the diff. The local edit must be moved to a source file or discarded explicitly.
- `doctor` reports when the output is older than its sources, for example after `git pull`.

An optional local Git `post-merge` hook may run `ai-config doctor`. It is read-only and is installed only by the user.

## Skills

### Install locations

- Codex personal skills are installed under `~/.agents/skills/<name>`.
- Claude personal skills are installed under `~/.claude/skills/<name>`.

The tool creates a separate symlink for each skill directory. It does not replace either complete `skills` directory, because those locations also contain bundled, synchronized, or application-managed skills.

### Legacy Codex location

Codex also loads skills from `$CODEX_HOME/skills` (`~/.codex/skills` by default). Its bundled skill creator and installer still write new skills there. Therefore:

- Migration moves every managed name out of `~/.codex/skills` before creating its link under `~/.agents/skills`. The old copy is backed up first.
- `~/.codex/skills/.system` is never touched.
- `doctor` always inspects both Codex locations and reports skills created by Codex in the legacy location as unmanaged.

### Duplicate names

`doctor` checks for duplicate skill names across every location an agent discovers skills from, not only the install target:

- Codex: `~/.agents/skills`, `~/.codex/skills` (including `.system`), and plugin skills.
- Claude: `~/.claude/skills` (including `synced/`), and plugin skills.

Both the directory name and the `name` field of `SKILL.md` are compared, without regard to letter case, because the default macOS file system is case-insensitive.

### Content rules

Shared skills use only features supported by both agents. Agent-specific frontmatter, commands, paths, tool assumptions, and runtime behavior stay in their owner's folder.

Each skill may declare required CLI programs, MCP servers, and supported versions. Missing dependencies produce a clear diagnostic. The management tool never installs system dependencies.

## Manifest

`manifest.json` is the installation allowlist. Files are not installed merely because they exist in the repository, and `doctor` fails when a skill directory in the repository has no manifest entry.

Each entry describes:

- A stable ID.
- The installation method: `symlink` or `compose`.
- Repository-relative sources.
- Local targets, written with a leading `~/`.
- Required dependencies, when applicable.

Example:

```json
{
  "version": 1,
  "entries": [
    {
      "id": "skill/agterm",
      "method": "symlink",
      "source": "shared/skills/agterm",
      "targets": ["~/.agents/skills/agterm", "~/.claude/skills/agterm"],
      "requires": { "commands": ["agtermctl"] }
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
scripts/ai-config adopt --agent <agent> --skill <name> [--replace-repo]
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
6. Target is a broken link or points outside this repository: conflict.
7. Link points into this repository but has no manifest entry (a removed or renamed skill): reported as a managed orphan and removed only with `--prune`.
8. Local content with no repository entry: reported as unmanaged and never changed.

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

`adopt` imports a local skill into the repository and adds its manifest entry. It runs the same security checks as `doctor` and refuses forbidden files. It never commits.

### Uninstall behavior

Uninstall removes only links and generated files that the state file records as created by this tool and that still match what was created. It never removes an ordinary local file. Restoring a backup is a separate explicit action.

### Backups

Every replaced or removed local entry is backed up under `backups/<backup-id>/` in the state directory:

- The backup directory is created with mode `0700` and backup files with mode `0600`, whatever the source mode was. Original modes are recorded in the backup metadata.
- The last 5 backups of each target are kept. Older ones are removed after a successful install.
- `restore <backup-id>` puts the backup back and restores the original modes. If the target is a managed link, restore replaces it. If the target is ordinary local content that differs from the backup, restore reports a conflict.

## Configuration management

The complete `~/.codex` and `~/.claude` directories, and any of their subfolders, must never be linked to the repository. They mix authored configuration with credentials, histories, sessions, caches, databases, downloaded plugins, device state, and automatic permission grants.

In version 1 the tool never writes `~/.codex/config.toml`, `~/.claude/settings.json`, `~/.claude.json`, or any rules file. `doctor` may read them to report missing dependencies of managed skills, such as a required MCP server.

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

A private Git repository is not treated as secret storage. `.gitignore`, local validation, and secret scanning provide separate layers of protection. `adopt` runs the same checks before importing local content.

Scripts inside skills are executable capabilities. Their code, dependencies, requested permissions, and data access must be reviewable. Synced content must not silently grant broad filesystem, shell, network, or external-service access.

## Validation and testing

`doctor` checks:

- JSON syntax of the manifest and state file.
- Required `SKILL.md` metadata.
- Invalid classifications and skill directories missing from the manifest.
- Duplicate skill names across all discovery locations.
- Missing referenced files, broken symlinks, and managed orphans.
- Generated output that is older than its sources or was edited locally.
- Script syntax and executable permissions.
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

The existing local configuration contains these known cases:

- `agterm` is identical in `~/.codex/skills` and `~/.claude/skills` and is a candidate for `shared/skills/`.
- `backlog` and `commit-me` differ between agents and require review before classification.
- Codex `claude-review` and `task-plan` are counterparts to Claude `codex-review` and `plan`. They stay agent-specific.
- `styles-handling` exists only under `~/.agents/skills` and requires classification.
- `~/.claude/skills/synced/` is cloud-synchronized and never managed.
- `~/.codex/AGENTS.md` and `~/.claude/CLAUDE.md` state the same policies in different words. Migration chooses one wording for `shared/instructions.md`.
- `~/.claude/rules/` does not exist yet and is created by the first install.

Each Codex skill is migrated in this order: classify it, adopt it into the repository, back up and remove the copy in `~/.codex/skills`, then link it into `~/.agents/skills`.

Migration never assumes that similarly named skills should be merged. Divergent content remains unchanged until reviewed.

## Platform assumption

The first implementation targets macOS and Linux. Windows support requires a separate decision about symlinks, path handling, and state-directory conventions.
